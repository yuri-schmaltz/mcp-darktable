from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
import logging

from common import (
    fetch_images,
    prepare_vision_payloads,
    prepare_vision_payloads_async,
    save_log,
    fallback_user_prompt,
    append_export_result_to_log,
    extract_export_errors
)
from prompts import get_prompt
from llm_api import LLMProvider

def build_messages(system_prompt: str, sample: list[dict], vision_images: list, provider_type: str = "ollama"):
    """
    Constrói mensagens para o LLM. 
    Se provider_type for 'ollama', usa formato específico (images lista base64).
    Se 'openai-compat', usa formato content array com image_url.
    """
    if not vision_images:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": fallback_user_prompt(sample)},
        ]

    messages = [{"role": "system", "content": system_prompt}]
    
    # Lógica unificada de loop nas imagens
    # ...
    # OBS: O formato de envio de imagem varia entre Ollama e OpenAI.
    # Ollama (nativo): { role: user, content: txt, images: [b64] }
    # OpenAI: { role: user, content: [ {type:text...}, {type:image_url...} ] }
    
    # Para simplificar, vamos iterar e adaptar aqui, ou delegar ao Provider.
    # Como a construção da mensagem depende do 'contract' do provider, 
    # idealmente o Provider deveria formatar. Mas vamos fazer cheque simples aqui.
    
    for item in vision_images:
        meta = item.meta
        colorlabels = ",".join(meta.get("colorlabels", []))
        description = (
            f"Image ID={meta.get('id')} Path={item.path} Rating={meta.get('rating')} "
            f"Labels=[{colorlabels}]"
        )
        from typing import cast, Any
        if provider_type == "ollama":
            # 'images' deve ser lista de strings (API Ollama)
            images_list = [item.b64] if isinstance(item.b64, str) else (item.b64 if isinstance(item.b64, list) else [])
            messages.append({
                "role": "user",
                "content": description,
                "images": cast(Any, images_list)
            })
        else:
            # OpenAI / LM Studio espera 'content' como lista de objetos
            content_list = [
                {"type": "text", "text": description},
                {"type": "image_url", "image_url": {"url": item.data_url}}
            ]
            messages.append({
                "role": "user",
                "content": cast(Any, content_list)
            })

    messages.append({
        "role": "user",
        "content": "Retorne APENAS um JSON com o plano de ação seguindo o schema."
    })
    return messages


def extract_json_from_markdown(text: str) -> str:
    """
    Extract JSON from markdown code blocks if present.
    Handles cases where LLM wraps JSON in ```json ... ``` blocks.
    """
    import re
    
    # Check for markdown code block with json language specifier
    pattern = r'```(?:json)?\s*\n(.*?)\n```'
    match = re.search(pattern, text, re.DOTALL)
    
    if match:
        return match.group(1).strip()
    
    # If no markdown block found, return original text
    return text.strip()



class BatchProcessor:
    def __init__(self, client, provider: LLMProvider, dry_run: bool = False):
        self.client = client
        self.provider = provider
        self.dry_run = dry_run
        # provider_type ajuda a decidir formato de mensagem
        self.provider_type = "ollama" if "Ollama" in provider.__class__.__name__ else "openai"

    def run(self, mode: str, args):
        method_name = f"run_mode_{mode}"
        if hasattr(self, method_name):
            return getattr(self, method_name)(args)
        else:
            logging.error(f"Modo desconhecido: {mode}")
            print(f"Modo desconhecido: {mode}")

    def _process_common(self, mode: str, args):
        # Log active configuration
        config_dict = {k: v for k, v in vars(args).items() if k not in ["func", "prompt_file"]}
        logging.info(f"[{mode}] Configuração ativa: {config_dict}")
        
        images = fetch_images(self.client, args)
        logging.info(f"[{mode}] Imagens filtradas: {len(images)}")
        if not images:
            return None, None

        sample = images[: args.limit]
        # Modular: carrega prompt via utilitário, com validação YAML
        try:
            system_prompt = get_prompt(mode, args.prompt_variant)
        except Exception as e:
            logging.error(f"Erro ao carregar prompt: {e}")
            print(f"[erro] Falha ao carregar prompt: {e}")
            return None, None
        # progress_callback não definido, definir como None por padrão
        vision_images, vision_errors = prepare_vision_payloads_async(
            sample,
            attach_images=not args.text_only,
            progress_callback=None,
            max_workers=4
        )
        
        if not vision_images and images and not args.text_only:
            logging.error("[erro] Nenhuma imagem encontrada no disco. Verifique se o drive está montado ou se o banco de dados do Darktable está atualizado.")
            print("[erro] Nenhuma imagem encontrada no disco. Verifique se o drive está montado ou se o banco de dados do Darktable está atualizado.")
            return None, None

        if vision_errors:
            logging.warning(f"[{mode}] Erros de imagem: {vision_errors}")

        messages = build_messages(system_prompt, sample, vision_images, self.provider_type)
        
        # Calculate approximate payload size
        import json as json_module
        payload_size_mb = len(json_module.dumps(messages)) / (1024 * 1024)
        
        logging.info(
            f"[{mode}] Enviando {len(vision_images)} imagem(ns) ao LLM ({self.provider.model}, payload: {payload_size_mb:.1f} MB)..."
        )
        logging.debug(f"[{mode}] Prompt System: {system_prompt[:100]}...")
        
        answer, meta = self.provider.chat(messages)
        
        answer_size_kb = len(answer) / 1024 if answer else 0
        logging.info(
            f"[{mode}] Resposta recebida ({meta.get('latency_ms', 0)}ms, {answer_size_kb:.1f} KB)"
        )

        log_file = save_log(mode, args.source, sample, answer, extra={"llm": meta})
        logging.info(f"[{mode}] Log: {log_file}")
        
        return answer, log_file

    def run_mode_rating(self, args):
        import time
        t0 = time.time()
        success = False
        error_msg = None
        answer, _ = self._process_common("rating", args)
        if not answer:
            self._log_metric("rating", success=False, duration=time.time()-t0, extra={"error": "no_answer"})
            return
        try:
            json_str = extract_json_from_markdown(answer)
            parsed = json.loads(json_str)
            edits = parsed.get("edits", [])
        except Exception as e:
            error_msg = str(e)
            logging.error(f"[rating] Erro JSON: {e}")
            logging.error(f"[rating] Resposta bruta do LLM:\n{answer}")
            print(f"[rating] Erro JSON: {e}")
            print(f"[rating] Resposta bruta do LLM:\n{answer}")
            self._log_metric("rating", success=False, duration=time.time()-t0, extra={"error": error_msg})
            return
        if not edits:
            logging.info("[rating] Nenhuma edição.")
            print("[rating] Nenhuma edição.")
            self._log_metric("rating", success=True, duration=time.time()-t0, extra={"edits": 0})
            return
        logging.info(f"[rating] {len(edits)} edições propostas:")
        print(f"[rating] {len(edits)} edições propostas:")
        for edit in edits:
            img_id = edit.get("id")
            new_rating = edit.get("rating")
            img_meta = next((img for img in sample if img.get("id") == img_id), None)
            if img_meta:
                filename = img_meta.get("filename", f"ID {img_id}")
                old_rating = img_meta.get("rating", "?")
                logging.info(f"  • {filename}: rating {old_rating} → {new_rating}")
                print(f"  • {filename}: rating {old_rating} → {new_rating}")
            else:
                logging.info(f"  • ID {img_id}: rating → {new_rating}")
                print(f"  • ID {img_id}: rating → {new_rating}")
        try:
            if self.dry_run:
                logging.info("[rating] DRY-RUN. Nenhuma ação tomada.")
                print("[rating] DRY-RUN. Nenhuma ação tomada.")
            else:
                res = self.client.call_tool("apply_batch_edits", {"edits": edits})
                result_text = res["content"][0]["text"]
                logging.info(f"[rating] {result_text}")
                print(f"[rating] {result_text}")
            success = True
        except Exception as e:
            error_msg = str(e)
            logging.error(f"[rating] Erro ao aplicar edits: {e}")
            print(f"[rating] Erro ao aplicar edits: {e}")
        self._log_metric("rating", success=success, duration=time.time()-t0, extra={"edits": len(edits), "error": error_msg} if error_msg else {"edits": len(edits)})

    def _log_metric(self, mode, success, duration, extra=None):
        """Loga métrica simples em logs/metrics.json."""
        import json, time
        from pathlib import Path
        metrics_path = Path(__file__).parent.parent / "logs" / "metrics.json"
        metrics_path.parent.mkdir(exist_ok=True)
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": mode,
            "success": success,
            "duration": round(duration, 3),
        }
        if extra:
            entry.update(extra)
        try:
            if metrics_path.exists():
                with open(metrics_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = []
        except Exception:
            data = []
        data.append(entry)
        try:
            with open(metrics_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"Falha ao gravar métricas: {e}")

    def run_mode_tagging(self, args):
        # Modular: carrega prompt via utilitário, com validação YAML
        from prompts import get_prompt
        try:
            _ = get_prompt("tagging", getattr(args, "prompt_variant", "basico"))
        except Exception as e:
            logging.error(f"Erro ao carregar prompt de tagging: {e}")
            print(f"[erro] Falha ao carregar prompt de tagging: {e}")
            return
        answer, _ = self._process_common("tagging", args)
        if not answer: return
        try:
            json_str = extract_json_from_markdown(answer)
            parsed = json.loads(json_str)
            tags = parsed.get("tags", [])
        except Exception as e:
            logging.error(f"[tagging] Erro JSON: {e}")
            print(f"[tagging] Erro JSON: {e}")
            return
        if self.dry_run:
            logging.info(f"[tagging] DRY-RUN. Tags: {tags}")
            print("[tagging] DRY-RUN. Tags:", tags)
            return
        for entry in tags:
            tag = entry.get("tag")
            ids = entry.get("ids", [])
            if tag and ids:
                self.client.call_tool("tag_batch", {"tag": tag, "ids": ids})
                tagged_files = [img.get("filename", f"ID {img.get('id')}") 
                               for img in sample if img.get("id") in ids]
                logging.info(f"[tagging] Tag '{tag}' aplicada em {len(ids)} foto(s):")
                print(f"[tagging] Tag '{tag}' aplicada em {len(ids)} foto(s):")
                for filename in tagged_files[:10]:
                    logging.info(f"  • {filename}")
                    print(f"  • {filename}")
                if len(tagged_files) > 10:
                    logging.info(f"  ... e mais {len(tagged_files) - 10} foto(s)")
                    print(f"  ... e mais {len(tagged_files) - 10} foto(s)")

    def run_mode_export(self, args):
        # Modular: carrega prompt via utilitário, com validação YAML
        from prompts import get_prompt
        try:
            _ = get_prompt("export", getattr(args, "prompt_variant", "basico"))
        except Exception as e:
            logging.error(f"Erro ao carregar prompt de export: {e}")
            print(f"[erro] Falha ao carregar prompt de export: {e}")
            return
        if not args.target_dir:
            print("[export] --target-dir obrigatório.")
            return
        answer, log_file = self._process_common("export", args)
        if not answer: return
        try:
            json_str = extract_json_from_markdown(answer)
            parsed = json.loads(json_str)
            ids = parsed.get("ids_para_exportar") or parsed.get("ids") or []
        except:
            return
        print(f"[export] {len(ids)} imagens para exportar.")
        if self.dry_run:
            return
        params = {"target_dir": args.target_dir, "ids": ids, "format": "jpg", "overwrite": False}
        res = self.client.call_tool("export_collection", params)
        print("[export] Resultado:", res["content"][0]["text"])
        if log_file:
            append_export_result_to_log(log_file, res)

    def run_mode_tratamento(self, args):
        # Modular: carrega prompt via utilitário, com validação YAML
        from prompts import get_prompt
        try:
            _ = get_prompt("tratamento", getattr(args, "prompt_variant", "basico"))
        except Exception as e:
            logging.error(f"Erro ao carregar prompt de tratamento: {e}")
            print(f"[erro] Falha ao carregar prompt de tratamento: {e}")
            return
        answer, _ = self._process_common("tratamento", args)
        if not answer: return
        try:
            json_str = extract_json_from_markdown(answer)
            parsed = json.loads(json_str)
            treatments = parsed.get("treatments", [])
        except Exception as e:
            logging.error(f"[tratamento] Erro JSON: {e}")
            print(f"[tratamento] Erro JSON: {e}")
            return
        if not treatments:
            logging.info("[tratamento] Nenhuma sugestão recebida.")
            print("[tratamento] Nenhuma sugestão recebida.")
            return
        logging.info(f"[tratamento] Processando {len(treatments)} sugestões...")
        print(f"[tratamento] Processando {len(treatments)} sugestões...")
        
        rating_edits = []
        color_edits = []
        
        for t in treatments:
            tid = t.get("id")
            if not tid: continue
            
            # Prepare batch edits (Ratings / Color Labels)
            if "rating" in t:
                rating_edits.append({"id": tid, "rating": t["rating"]})
            if "color_label" in t:
                color_edits.append({"id": tid, "color": t["color_label"]})
            
            # Handle Style Generation (Exposure)
            style_params = {}
            changes = []
            
            if "rating" in t: changes.append(f"Rating {t['rating']}")
            if "color_label" in t: changes.append(f"Label {t['color_label']}")
            
            # Check for exposure adjustment in JSON
            # Expecting schema extension: "exposure": 0.5
            if "exposure" in t:
                try:
                    ev = float(t["exposure"])
                    if abs(ev) > 0.01: # Ignore near-zero
                        style_params["exposure"] = ev
                        changes.append(f"Exposure {ev:+.2f}")
                except (ValueError, TypeError):
                    pass
            
            # Log suggestion
            img_meta = next((img for img in (fetch_images(self.client, args) or []) if img.get("id") == tid), None)
            name = img_meta.get("filename", f"ID {tid}") if img_meta else f"ID {tid}"
            notes = t.get("notes", "")

            logging.info(f"  • {name}: {', '.join(changes)}")
            print(f"  • {name}: {', '.join(changes)}")
            if notes:
                logging.info(f"    Sugestão: {notes}")
                print(f"    Sugestão: {notes}")
            
            # Generate and Apply Style if needed
            generate_styles = getattr(args, "generate_styles", True) # Default to True if missing
            if generate_styles and style_params and not self.dry_run:
                try:
                    from style_generator import DarktableStyleGenerator
                    generator = DarktableStyleGenerator(Path.home() / ".config/darktable/styles/mcp_generated")
                    
                    style_name = f"MCP Auto {tid} Exp{style_params['exposure']:+.1f}"
                    style_path = generator.generate_style(style_name, style_params)
                    
                    # Import and Apply (Requires new tools support)
                    # We send the path to the server to import
                    # Then apply by name
                    
                    # Tool: import_style(path)
                    res_imp = self.client.call_tool("import_style", {"style_path": str(style_path)})
                    
                    # Tool: apply_style(style_name, image_id)
                    # Note: We can batch if many images get SAME style, but here it's per-image specific
                    res_app = self.client.call_tool("apply_style", {"style_name": style_name, "image_ids": [tid]})
                    
                    logging.info(f"    [style] Estilo '{style_name}' criado e aplicado.")
                    print(f"    [style] Estilo '{style_name}' criado e aplicado.")
                except Exception as e:
                    logging.error(f"    [style] Erro ao aplicar estilo: {e}")
                    print(f"    [style] Erro ao aplicar estilo: {e}")
            elif style_params and self.dry_run:
                logging.info(f"    [style] DRY-RUN: Estilo seria criado comparams {style_params}")
                print(f"    [style] DRY-RUN: Estilo seria criado comparams {style_params}")

        if self.dry_run:
            logging.info("[tratamento] DRY-RUN. Nenhuma alteração aplicada.")
            print("[tratamento] DRY-RUN. Nenhuma alteração aplicada.")
            return

        # Apply Ratings and Colors
        if rating_edits and not self.dry_run:
            try:
                self.client.call_tool("apply_batch_edits", {"edits": rating_edits})
                logging.info(f"[tratamento] Ratings aplicados em {len(rating_edits)} imagens.")
                print(f"[tratamento] Ratings aplicados em {len(rating_edits)} imagens.")
            except Exception as e:
                logging.error(f"[tratamento] Erro ao aplicar ratings: {e}")
                print(f"[tratamento] Erro ao aplicar ratings: {e}")

        if color_edits and not self.dry_run:
            try:
                self.client.call_tool("set_colorlabel_batch", {"edits": color_edits, "overwrite": True})
                logging.info(f"[tratamento] Color labels aplicados em {len(color_edits)} imagens.")
                print(f"[tratamento] Color labels aplicados em {len(color_edits)} imagens.")
            except Exception as e:
                logging.error(f"[tratamento] Erro ao aplicar color labels: {e}")
                print(f"[tratamento] Erro ao aplicar color labels: {e}")
        if self.dry_run:
            logging.info("[tratamento] DRY-RUN. Nenhuma alteração aplicada.")
            print("[tratamento] DRY-RUN. Nenhuma alteração aplicada.")
            return

        # Apply Ratings
        if rating_edits:
            try:
                self.client.call_tool("apply_batch_edits", {"edits": rating_edits})
                print(f"[tratamento] Ratings aplicados em {len(rating_edits)} imagens.")
            except Exception as e:
                print(f"[tratamento] Erro ao aplicar ratings: {e}")

        # Apply Color Labels
        if color_edits:
            try:
                # Group by color because API might imply single color batch or loop handles it?
                # tool_set_colorlabel_batch takes list of {id, color}.
                self.client.call_tool("set_colorlabel_batch", {"edits": color_edits, "overwrite": True})
                print(f"[tratamento] Color labels aplicados em {len(color_edits)} imagens.")
            except Exception as e:
                print(f"[tratamento] Erro ao aplicar color labels: {e}")
    
    def run_mode_completo(self, args):
        logging.info("="*60)
        logging.info("[completo] INICIANDO PIPELINE COMPLETE (Rating -> Tagging -> Tratamento -> Export)")
        logging.info("="*60)
        print("="*60)
        print("[completo] INICIANDO PIPELINE COMPLETE (Rating -> Tagging -> Tratamento -> Export)")
        print("="*60)
        
        print("\n--- ETAPA 1: RATING ---\n")
        self.run_mode_rating(args)
        
        print("\n--- ETAPA 2: TAGGING ---\n")
        self.run_mode_tagging(args)
        
        print("\n--- ETAPA 3: TRATAMENTO ---\n")
        self.run_mode_tratamento(args)
        
        print("\n--- ETAPA 4: EXPORT ---\n")
        self.run_mode_export(args)
        
        logging.info("\n" + "="*60)
        logging.info("[completo] PIPELINE FINALIZADO")
        logging.info("="*60)
        print("\n" + "="*60)
        print("[completo] PIPELINE FINALIZADO")
        print("="*60)
