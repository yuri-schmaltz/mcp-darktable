from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
import logging

from common import (
    fetch_images,
    load_prompt,
    prepare_vision_payloads,
    save_log,
    fallback_user_prompt,
    append_export_result_to_log,
    extract_export_errors
)
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
        
        if provider_type == "ollama":
            messages.append({
                "role": "user", 
                "content": description, 
                "images": [item.b64]
            })
        else:
            # OpenAI / LM Studio
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": description},
                    {"type": "image_url", "image_url": {"url": item.data_url}}
                ]
            })

    messages.append({
        "role": "user",
        "content": "Retorne APENAS um JSON com o plano de ação seguindo o schema."
    })
    return messages


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
            print(f"Modo desconhecido: {mode}")

    def _process_common(self, mode: str, args):
        images = fetch_images(self.client, args)
        logging.info(f"[{mode}] Imagens filtradas: {len(images)}")
        if not images:
            return None, None

        sample = images[: args.limit]
        system_prompt = load_prompt(mode, args.prompt_file, variant=args.prompt_variant)
        vision_images, vision_errors = prepare_vision_payloads(sample, attach_images=not args.text_only)
        
        if not vision_images and images and not args.text_only:
            print("[erro] Nenhuma imagem encontrada no disco. Verifique se o drive está montado ou se o banco de dados do Darktable está atualizado.")
            return None, None

        if vision_errors:
            logging.warning(f"[{mode}] Erros de imagem: {vision_errors}")

        messages = build_messages(system_prompt, sample, vision_images, self.provider_type)
        
        logging.info(f"[{mode}] Enviando requisição ao LLM ({self.provider.model})...")
        logging.debug(f"[{mode}] Prompt System: {system_prompt[:100]}...")
        
        answer, meta = self.provider.chat(messages)
        logging.info(f"[{mode}] Resposta recebida ({meta.get('latency_ms', 0)}ms)")

        log_file = save_log(mode, args.source, sample, answer, extra={"llm": meta})
        logging.info(f"[{mode}] Log: {log_file}")
        
        return answer, log_file

    def run_mode_rating(self, args):
        answer, _ = self._process_common("rating", args)
        if not answer: return

        try:
            parsed = json.loads(answer)
            edits = parsed.get("edits", [])
        except Exception as e:
            print(f"[rating] Erro JSON: {e}")
            print(f"[rating] Resposta bruta do LLM:\n{answer}")
            return

        if not edits:
            print("[rating] Nenhuma edição.")
            return

        print(f"[rating] {len(edits)} edições propostas.")
        if self.dry_run:
            print("[rating] DRY-RUN. Nenhuma ação tomada.")
        else:
            res = self.client.call_tool("apply_batch_edits", {"edits": edits})
            print("[rating] Resultado:", res["content"][0]["text"])

    def run_mode_tagging(self, args):
        answer, _ = self._process_common("tagging", args)
        if not answer: return

        try:
            parsed = json.loads(answer)
            tags = parsed.get("tags", [])
        except Exception as e:
            print(f"[tagging] Erro JSON: {e}")
            return
            
        if self.dry_run:
            print("[tagging] DRY-RUN. Tags:", tags)
            return

        for entry in tags:
            tag = entry.get("tag")
            ids = entry.get("ids", [])
            if tag and ids:
                self.client.call_tool("tag_batch", {"tag": tag, "ids": ids})
                print(f"[tagging] Aplicado '{tag}' em {len(ids)} fotos.")

    def run_mode_export(self, args):
        if not args.target_dir:
            print("[export] --target-dir obrigatório.")
            return

        answer, log_file = self._process_common("export", args)
        if not answer: return

        try:
            parsed = json.loads(answer)
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
        # Tratamento geralmente só gera plano, não aplica ação automática no darktable (ainda)
        answer, _ = self._process_common("tratamento", args)
        if answer:
            print("[tratamento] Plano gerado (ver log ou saída acima).")
    
    def run_mode_completo(self, args):
        print("[completo] Executando pipeline completo...")
        self.run_mode_rating(args)
        self.run_mode_tagging(args)
        self.run_mode_tratamento(args)
        self.run_mode_export(args)
