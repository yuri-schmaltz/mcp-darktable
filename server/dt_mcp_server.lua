#!/usr/bin/env lua

--------------------------------------------------
-- Servidor MCP para darktable (v2)
-- - list_collection
-- - list_by_path
-- - list_by_tag
-- - apply_batch_edits (rating)
-- - set_colorlabel_batch
-- - tag_batch
-- - export_collection (com suporte a ids)
--------------------------------------------------

local json   = require "dkjson"
local package = require "package"

local function mcp_error(message, code, field, extra)
  local json_error = {
    code    = code or "validation_error",
    message = message,
    field   = field
  }

  if extra then
    for k, v in pairs(extra) do
      json_error[k] = v
    end
  end

  return {
    content = {
      { type = "text", text = message },
      { type = "json", json = json_error }
    },
    isError = true
  }
end

local PROTOCOL_VERSION = "2024-11-05"

--------------------------------------------------
-- 1. Inicializar darktable em modo biblioteca
--------------------------------------------------

-- Ajuste esse caminho conforme sua distro:
-- Ex: /usr/lib/darktable/libdarktable.so
package.cpath = package.cpath .. ";/usr/lib/darktable/lib?.so"

local dt = require("darktable")(
  "--library",   os.getenv("HOME") .. "/.config/darktable/library.db",
  "--datadir",   "/usr/share/darktable",
  "--moduledir", "/usr/lib/darktable",
  "--configdir", os.getenv("HOME") .. "/.config/darktable",
  "--cachedir",  os.getenv("HOME") .. "/.cache/darktable"
)

--------------------------------------------------
-- 2. Helpers JSON-RPC / MCP
--------------------------------------------------

local function send_response(obj)
  local s = json.encode(obj, { indent = false })
  io.stdout:write(s, "\n")
  io.stdout:flush()
end

local function send_error(id, code, message)
  send_response{
    jsonrpc = "2.0",
    id = id,
    error = {
      code = code or -32603,
      message = message or "Internal error"
    }
  }
end

--------------------------------------------------
-- 3. Helpers de imagens / metadata
--------------------------------------------------

local function safe_colorlabels(img)
  -- devolve lista de cores ativas, só pra informação
  local colors = { "red", "yellow", "green", "blue", "purple" }
  local out = {}
  if not img.colorlabels then return out end
  for i, name in ipairs(colors) do
    -- índices normalmente 0..4; aqui assumo 1..5 se dt normalizar
    if img.colorlabels[i-1] or img.colorlabels[i] then
      table.insert(out, name)
    end
  end
  return out
end

local function image_to_metadata(img)
  return {
    id         = img.id,
    path       = img.path,
    filename   = img.filename,
    rating     = img.rating,
    is_raw     = img.is_raw,
    colorlabels = safe_colorlabels(img),
  }
end

local function command_exists(cmd)
  local check_cmd = string.format("command -v %s >/dev/null 2>&1", cmd)
  local result = os.execute(check_cmd)
  if type(result) == "number" then
    return result == 0
  end
  return result == true
end

--------------------------------------------------
-- 4. Ferramentas MCP (lado darktable)
--------------------------------------------------

--------------------------------------------------
-- 4.1 list_collection
-- args: { min_rating?: number, only_raw?: boolean }
--------------------------------------------------
local function tool_list_collection(args)
  args = args or {}
  local min_rating = args.min_rating or -2
  local only_raw   = args.only_raw or false

  local result = {}

  for _, img in ipairs(dt.database) do
    if (not only_raw or img.is_raw) and (img.rating or 0) >= min_rating then
      table.insert(result, image_to_metadata(img))
    end
  end

  return {
    content = {
      { type = "json", json = result }
    },
    isError = false
  }
end

--------------------------------------------------
-- 4.2 list_by_path
-- args: { path_contains: string, min_rating?: number, only_raw?: boolean }
--------------------------------------------------
local function tool_list_by_path(args)
  args = args or {}
  local path_contains = args.path_contains or ""
  local min_rating    = args.min_rating or -2
  local only_raw      = args.only_raw or false

  local result = {}

  for _, img in ipairs(dt.database) do
    local p = img.path or ""
    if p:find(path_contains, 1, true) then
      if (not only_raw or img.is_raw) and (img.rating or 0) >= min_rating then
        table.insert(result, image_to_metadata(img))
      end
    end
  end

  return {
    content = {
      { type = "json", json = result }
    },
    isError = false
  }
end

--------------------------------------------------
-- 4.3 list_by_tag
-- args: { tag: string, min_rating?: number, only_raw?: boolean }
--------------------------------------------------
local function tool_list_by_tag(args)
  args = args or {}
  local tag_name   = args.tag
  local min_rating = args.min_rating or -2
  local only_raw   = args.only_raw or false

  if not tag_name then
    return {
      content = { { type = "text", text = "tag é obrigatória" } },
      isError = true
    }
  end

  local tag = dt.tags.create(tag_name)
  local images = dt.tags.get_images(tag)
  local result = {}

  for _, img in ipairs(images) do
    if (not only_raw or img.is_raw) and (img.rating or 0) >= min_rating then
      table.insert(result, image_to_metadata(img))
    end
  end

  return {
    content = {
      { type = "json", json = result }
    },
    isError = false
  }
end

--------------------------------------------------
-- 4.4 apply_batch_edits (rating)
-- args: { edits: [ { id: number, rating?: number } ] }
--------------------------------------------------
local function tool_apply_batch_edits(args)
  if not args or type(args.edits) ~= "table" then
    return {
      content = { { type = "text", text = "Missing 'edits' array" } },
      isError = true
    }
  end

  local updated = 0
  for _, e in ipairs(args.edits) do
    if e.id then
      local img = dt.database[e.id]
      if img then
        if e.rating ~= nil then
          img.rating = e.rating
        end
        updated = updated + 1
      end
    end
  end

  return {
    content = {
      { type = "text", text = string.format("Applied rating edits to %d images", updated) }
    },
    isError = false
  }
end

--------------------------------------------------
-- 4.5 set_colorlabel_batch
-- args: { edits: [ { id: number, color: string } ] }
--------------------------------------------------
local color_map = {
  red    = 0,
  yellow = 1,
  green  = 2,
  blue   = 3,
  purple = 4
}

local function tool_set_colorlabel_batch(args)
  if not args or type(args.edits) ~= "table" then
    return {
      content = { { type = "text", text = "Missing 'edits' array" } },
      isError = true
    }
  end

  local updated = 0
  for _, e in ipairs(args.edits) do
    if e.id and e.color then
      local img = dt.database[e.id]
      local idx = color_map[e.color]
      if img and idx ~= nil then
        -- limpa todas as cores antes? aqui vou só ativar a pedida
        img.colorlabels[idx] = true
        updated = updated + 1
      end
    end
  end

  return {
    content = {
      { type = "text", text = string.format("Applied colorlabels to %d images", updated) }
    },
    isError = false
  }
end

--------------------------------------------------
-- 4.6 tag_batch
-- args: { tag: string, ids: [ number ] }
--------------------------------------------------
local function tool_tag_batch(args)
  if not args or not args.tag or type(args.ids) ~= "table" then
    return {
      content = { { type = "text", text = "tag e ids são obrigatórios" } },
      isError = true
    }
  end

  local tag = dt.tags.create(args.tag)
  local count = 0

  for _, id in ipairs(args.ids) do
    local img = dt.database[id]
    if img then
      dt.tags.attach(tag, img)
      count = count + 1
    end
  end

  return {
    content = {
      { type = "text", text = string.format("Tag '%s' aplicada a %d imagens", args.tag, count) }
    },
    isError = false
  }
end

--------------------------------------------------
-- 4.7 export_collection
-- args: {
--   target_dir: string,
--   ids?: [ number ],
--   format?: string,
--   overwrite?: boolean
-- }
-- OBS: usa darktable-cli externo, ajuste o comando se necessário.
--------------------------------------------------
local ALLOWED_EXPORT_FORMATS = { "jpg", "jpeg", "tif", "tiff", "png", "webp" }
local ALLOWED_EXPORT_FORMATS_SET = {}
for _, fmt in ipairs(ALLOWED_EXPORT_FORMATS) do
  ALLOWED_EXPORT_FORMATS_SET[fmt] = true
end

local function tool_export_collection(args)
  args = args or {}
  local target_dir = args.target_dir
  if not target_dir then
    return mcp_error("target_dir is required", "missing_target_dir", "target_dir")
  end

  if type(target_dir) ~= "string" or target_dir == "" then
    return mcp_error("target_dir deve ser string não vazia", "invalid_target_dir", "target_dir")
  end

  if target_dir:find("\n") or target_dir:find("\r") then
    return mcp_error(
      "target_dir não pode conter quebras de linha",
      "invalid_target_dir",
      "target_dir"
    )
  end

  if target_dir:find("%.%.", 1, true) then
    return mcp_error(
      "target_dir não pode conter '..'",
      "invalid_target_dir",
      "target_dir"
    )
  end

  if target_dir:match("[><|;&%$`]") or target_dir:find("$(", 1, true) then
    return mcp_error(
      "target_dir não pode conter redirecionamentos ou caracteres de shell",
      "invalid_target_dir",
      "target_dir"
    )
  end

  local format    = (args.format or "jpg"):lower()
  local overwrite = args.overwrite or false

  if not format:match("^[%w]+$") then
    return mcp_error("format deve conter apenas letras/números", "invalid_format", "format")
  end

  if not ALLOWED_EXPORT_FORMATS_SET[format] then
    return mcp_error(
      "format não é suportado",
      "invalid_format",
      "format",
      { allowed = ALLOWED_EXPORT_FORMATS }
    )
  end

  if not command_exists("darktable-cli") then
    return {
      content = { { type = "text", text = "darktable-cli não encontrado no PATH" } },
      isError = true
    }
  end

  -- garantir que target_dir existe
  os.execute(string.format('mkdir -p "%s"', target_dir))

  -- montar lista de imagens a exportar
  local to_export = {}

  if type(args.ids) == "table" then
    for _, id in ipairs(args.ids) do
      local img = dt.database[id]
      if img then
        table.insert(to_export, img)
      end
    end
  else
    -- se não passar ids, exporta toda a coleção
    for _, img in ipairs(dt.database) do
      table.insert(to_export, img)
    end
  end

  local exported = 0
  local errors = {}
  for _, img in ipairs(to_export) do
    local input = img.path .. "/" .. img.filename

    -- mudar extensão de saída pro formato escolhido
    local base = img.filename:gsub("%.[^%.]+$", "") -- tira extensão
    local out  = string.format("%s/%s.%s", target_dir, base, format)

    if not overwrite then
      local f = io.open(out, "r")
      if f then
        f:close()
        -- pula se já existe
        goto continue
      end
    end

    -- comando simples; ajuste flags conforme sua necessidade
    local cmd = string.format('darktable-cli "%s" "%s"', input, out)
    local ok, _, status = os.execute(cmd)
    local success = (type(ok) == "number" and ok == 0) or ok == true
    local exit_code = status or ok

    if success then
      exported = exported + 1
    else
      table.insert(errors, {
        id = img.id,
        input = input,
        output = out,
        command = cmd,
        exit = exit_code,
      })
      io.stderr:write(string.format(
        "[export_collection] falha exportando id=%s exit=%s\n",
        tostring(img.id),
        tostring(exit_code)
      ))
    end

    ::continue::
  end

  local summary = string.format("Exportadas %d imagens para %s", exported, target_dir)
  if #errors > 0 then
    summary = string.format("%s (%d falharam)", summary, #errors)
  end

  local content = {
    { type = "text", text = summary }
  }
  if #errors > 0 then
    table.insert(content, { type = "json", json = { errors = errors } })
  end

  return {
    content = content,
    isError = #errors > 0
  }
end

--------------------------------------------------
-- 5. Despacho MCP
--------------------------------------------------

local function handle_initialize(req)
  local params = req.params or {}
  local client_protocol = params.protocolVersion

  if client_protocol and client_protocol ~= PROTOCOL_VERSION then
    send_error(req.id, -32603, "Unsupported protocolVersion: " .. tostring(client_protocol))
    return
  end

  send_response{
    jsonrpc = "2.0",
    id = req.id,
    result = {
      protocolVersion = PROTOCOL_VERSION,
      serverInfo = {
        name = "darktable-mcp-batch",
        version = "0.2.0"
      },
      capabilities = {
        tools = {
          listChanged = false
        }
      }
    }
  }
end

local function handle_tools_list(req)
  local tools = {
    {
      name        = "list_collection",
      title       = "Listar coleção do darktable",
      description = "Lista imagens da biblioteca com filtros simples (min_rating, only_raw).",
      inputSchema = {
        type       = "object",
        properties = {
          min_rating = {
            type        = "number",
            description = "Rating mínimo (0–5, -1 rejeitado)."
          },
          only_raw = {
            type        = "boolean",
            description = "Se true, retorna apenas arquivos RAW."
          }
        }
      }
    },
    {
      name        = "list_by_path",
      title       = "Listar por caminho",
      description = "Lista imagens cujo path contém um trecho específico.",
      inputSchema = {
        type       = "object",
        required   = { "path_contains" },
        properties = {
          path_contains = {
            type        = "string",
            description = "Trecho do caminho (ex.: '2024-viagem-mg')."
          },
          min_rating = {
            type        = "number",
            description = "Rating mínimo."
          },
          only_raw = {
            type        = "boolean",
            description = "Apenas RAW."
          }
        }
      }
    },
    {
      name        = "list_by_tag",
      title       = "Listar por tag",
      description = "Lista imagens associadas a uma tag específica.",
      inputSchema = {
        type       = "object",
        required   = { "tag" },
        properties = {
          tag = {
            type        = "string",
            description = "Nome da tag (ex.: 'job:cliente-x')."
          },
          min_rating = {
            type        = "number",
            description = "Rating mínimo."
          },
          only_raw = {
            type        = "boolean",
            description = "Apenas RAW."
          }
        }
      }
    },
    {
      name        = "apply_batch_edits",
      title       = "Aplicar edições em lote (rating)",
      description = "Aplica rating em lote por ID.",
      inputSchema = {
        type       = "object",
        required   = { "edits" },
        properties = {
          edits = {
            type = "array",
            items = {
              type       = "object",
              required   = { "id" },
              properties = {
                id     = { type = "number", description = "ID da imagem no banco do darktable" },
                rating = { type = "number", description = "Novo rating (-1 a 5)" }
              }
            }
          }
        }
      }
    },
    {
      name        = "set_colorlabel_batch",
      title       = "Aplicar colorlabel em lote",
      description = "Marca colorlabels em lote por ID.",
      inputSchema = {
        type       = "object",
        required   = { "edits" },
        properties = {
          edits = {
            type = "array",
            items = {
              type       = "object",
              required   = { "id", "color" },
              properties = {
                id    = { type = "number", description = "ID da imagem no banco" },
                color = {
                  type        = "string",
                  description = "Uma das: red, yellow, green, blue, purple"
                }
              }
            }
          }
        }
      }
    },
    {
      name        = "tag_batch",
      title       = "Aplicar tag em lote",
      description = "Aplica uma mesma tag em várias imagens.",
      inputSchema = {
        type       = "object",
        required   = { "tag", "ids" },
        properties = {
          tag = {
            type        = "string",
            description = "Nome da tag (ex.: 'job:cliente-x')."
          },
          ids = {
            type  = "array",
            items = {
              type        = "number",
              description = "ID da imagem"
            }
          }
        }
      }
    },
    {
      name        = "export_collection",
      title       = "Exportar coleção",
      description = "Exporta imagens para um diretório (toda a coleção ou apenas ids específicos).",
      inputSchema = {
        type       = "object",
        required   = { "target_dir" },
        properties = {
          target_dir = {
            type        = "string",
            description = "Diretório de destino."
          },
          ids = {
            type  = "array",
            items = {
              type        = "number",
              description = "IDs das imagens a exportar (opcional)."
            }
          },
          format = {
            type        = "string",
            description = "Extensão de saída (jpg, tif, etc)."
          },
          overwrite = {
            type        = "boolean",
            description = "Se true, sobrescreve arquivos existentes."
          }
        }
      }
    }
  }

  send_response{
    jsonrpc = "2.0",
    id = req.id,
    result = {
      tools      = tools,
      nextCursor = nil
    }
  }
end

local function handle_tools_call(req)
  local params = req.params or {}
  local name   = params.name
  local args   = params.arguments or {}

  local result

  if name == "list_collection" then
    result = tool_list_collection(args)
  elseif name == "list_by_path" then
    result = tool_list_by_path(args)
  elseif name == "list_by_tag" then
    result = tool_list_by_tag(args)
  elseif name == "apply_batch_edits" then
    result = tool_apply_batch_edits(args)
  elseif name == "set_colorlabel_batch" then
    result = tool_set_colorlabel_batch(args)
  elseif name == "tag_batch" then
    result = tool_tag_batch(args)
  elseif name == "export_collection" then
    result = tool_export_collection(args)
  else
    send_error(req.id, -32601, "Unknown tool: " .. tostring(name))
    return
  end

  send_response{
    jsonrpc = "2.0",
    id      = req.id,
    result  = result
  }
end

local function dispatch(req)
  if req.method == "initialize" then
    handle_initialize(req)
  elseif req.method == "tools/list" then
    handle_tools_list(req)
  elseif req.method == "tools/call" then
    handle_tools_call(req)
  else
    send_error(req.id, -32601, "Unknown method: " .. tostring(req.method))
  end
end

--------------------------------------------------
-- 6. Loop principal (stdin/stdout)
--------------------------------------------------

for line in io.lines() do
  if line ~= "" then
    local req, pos, err = json.decode(line, 1, nil)
    if not req then
      send_error(nil, -32700, "Parse error: " .. tostring(err))
    else
      local ok, e = pcall(dispatch, req)
      if not ok then
        send_error(req.id, -32603, "Exception: " .. tostring(e))
      end
    end
  end
end
