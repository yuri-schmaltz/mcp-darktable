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

local function get_script_dir()
  local source = debug.getinfo(1, "S").source
  if source:sub(1, 1) == "@" then
    return source:sub(2):match("(.*/)") or "./"
  end
  return "./"
end

local script_dir = get_script_dir()
package.path = package.path .. ";" .. script_dir .. "?.lua"

local json   = require "dkjson"
local package = require "package"

local function command_exists(cmd)
  local check_cmd = string.format("command -v %s >/dev/null 2>&1", cmd)
  local result = os.execute(check_cmd)
  if type(result) == "number" then
    return result == 0
  end
  return result == true
end

local function file_exists(path)
  local f = io.open(path, "r")
  if f then
    f:close()
    return true
  end
  return false
end

local function dir_exists(path)
  local ok, _, code = os.rename(path, path)
  if ok then return true end
  return code == 13
end

local function detect_darktable_paths()
  local home = os.getenv("HOME") or ""

  local function add_candidate(list, prefix, source)
    if prefix and prefix ~= "" then
      table.insert(list, { prefix = prefix, source = source })
    end
  end

  local candidates = {}
  add_candidate(candidates, os.getenv("DARKTABLE_PREFIX"), "env:DARKTABLE_PREFIX")
  add_candidate(candidates, os.getenv("DARKTABLE_FLATPAK_PREFIX"), "env:DARKTABLE_FLATPAK_PREFIX")
  if home ~= "" then
    add_candidate(
      candidates,
      home .. "/.local/share/flatpak/app/org.darktable.Darktable/current/active/files",
      "flatpak:user"
    )
  end
  add_candidate(candidates, "/var/lib/flatpak/app/org.darktable.Darktable/current/active/files", "flatpak:system")
  add_candidate(candidates, "/usr", "default:/usr")
  add_candidate(candidates, "/usr/local", "default:/usr/local")

  local function pick_prefix()
    for _, item in ipairs(candidates) do
      local prefix = item.prefix
      local lib_candidates = {
        prefix .. "/lib/libdarktable.so",
        prefix .. "/lib64/libdarktable.so",
        prefix .. "/lib/darktable/libdarktable.so",
        prefix .. "/lib64/darktable/libdarktable.so",
      }
      for _, lib_path in ipairs(lib_candidates) do
        if file_exists(lib_path) then
          return item, lib_path
        end
      end
    end
    return nil, nil
  end

  local chosen, lib_path = pick_prefix()
  if not chosen then
    return {
      prefix    = "/usr",
      source    = "fallback",
      is_flatpak = false,
      lib_path  = "/usr/lib/darktable/libdarktable.so",
      datadir   = "/usr/share/darktable",
      moduledir = "/usr/lib/darktable",
      cpaths    = {
        "/usr/lib/lib?.so",
        "/usr/lib64/lib?.so",
        "/usr/lib/darktable/lib?.so",
        "/usr/lib64/darktable/lib?.so",
      }
    }
  end

  local moduledir = chosen.prefix .. "/lib/darktable"
  if dir_exists(chosen.prefix .. "/lib64/darktable") then
    moduledir = chosen.prefix .. "/lib64/darktable"
  end

  local cpaths = {
    chosen.prefix .. "/lib/lib?.so",
    chosen.prefix .. "/lib64/lib?.so",
    chosen.prefix .. "/lib/?.so",
    chosen.prefix .. "/lib64/?.so",
    chosen.prefix .. "/lib/darktable/lib?.so",
    chosen.prefix .. "/lib64/darktable/lib?.so",
    chosen.prefix .. "/lib/darktable/?.so",
    chosen.prefix .. "/lib64/darktable/?.so",
  }

  return {
    prefix     = chosen.prefix,
    source     = chosen.source,
    is_flatpak = chosen.source:find("flatpak", 1, true) ~= nil,
    lib_path   = lib_path,
    datadir    = chosen.prefix .. "/share/darktable",
    moduledir  = moduledir,
    cpaths     = cpaths,
  }
end

local dt_paths = detect_darktable_paths()

local function get_flatpak_runtime_libs()
  local handle = io.popen("flatpak info org.darktable.Darktable")
  if not handle then return {} end
  local content = handle:read("*a")
  handle:close()

  if not content then return {} end

  -- Busca linha "Runtime: ..." (funciona em inglês e pt-br se o label for "Runtime:")
  local runtime_ref = content:match("Runtime: ([%S]+)")
  if not runtime_ref then return {} end

  -- Formato esperado: id/arch/branch (ex: org.gnome.Platform/x86_64/49)
  local parts = {}
  for part in runtime_ref:gmatch("[^/]+") do
     table.insert(parts, part)
  end
  if #parts ~= 3 then return {} end
  
  local id, arch, branch = parts[1], parts[2], parts[3]
  
  -- Tentativa de localizar em system ou user flatpak
  local bases = {
      "/var/lib/flatpak/runtime/" .. id .. "/" .. arch .. "/" .. branch .. "/active/files",
      os.getenv("HOME") .. "/.local/share/flatpak/runtime/" .. id .. "/" .. arch .. "/" .. branch .. "/active/files"
  }

  local found_paths = {}
  for _, base in ipairs(bases) do
      if dir_exists(base) then
          table.insert(found_paths, base .. "/lib")
          -- Adiciona paths comuns de distros (ex: x86_64-linux-gnu)
          table.insert(found_paths, base .. "/lib/" .. arch .. "-linux-gnu")
          -- Fallback genérico caso a distro do runtime seja diferente
          table.insert(found_paths, base .. "/lib64")
      end
  end
  
  return found_paths
end

local function ensure_ld_library_path()
  if not dt_paths.is_flatpak then
    return
  end

  if os.getenv("DT_MCP_LD_REEXEC") == "1" then
    io.stderr:write("[init] LD_LIBRARY_PATH already injected\n")
    return
  end

  local ld_library_path = os.getenv("LD_LIBRARY_PATH") or ""
  local extra_paths = {}

  for _, dir in ipairs({ dt_paths.prefix .. "/lib", dt_paths.prefix .. "/lib64" }) do
    if dir_exists(dir) and not ld_library_path:find(dir, 1, true) then
      table.insert(extra_paths, dir)
    end
  end

  -- Injeta bibliotecas do Runtime Flatpak (ex: libxml2)
  for _, dir in ipairs(get_flatpak_runtime_libs()) do
    if dir_exists(dir) and not ld_library_path:find(dir, 1, true) then
       table.insert(extra_paths, dir)
    end
  end

  if #extra_paths == 0 then
    -- Mesmo sem libs extras, se temos um lua estático, podemos querer usá-lo 
    -- mas a lógica original só dava return. Vamos continuar se tivermos o binário static.
  end

  local new_ld_path = table.concat(extra_paths, ":")
  if ld_library_path ~= "" then
    new_ld_path = new_ld_path .. ":" .. ld_library_path
  end

  local script = debug.getinfo(1, "S").source or arg[0]
  if script:sub(1, 1) == "@" then
    script = script:sub(2)
  end

  -- Tenta localizar o lua-static no diretório host/ (pai de server/) ou no mesmo dir
  -- script está em server/dt_mcp_server.lua (normalmente)
  -- buscamos ../host/lua-static
  local script_dir = script:match("(.*/)") or "./"
  local static_lua_path = script_dir .. "../host/lua-static"
  
  -- Resolve path absoluto ou normaliza se possível, mas aqui vamos tentar executar direto 
  -- se o arquivo existir.
  local interpreter = arg and arg[-1] or "lua"
  
  if file_exists(static_lua_path) then
    -- Se achamos o estático, usamos ele. Precisamos garantir permissão x, mas já fizemos chmod.
    interpreter = static_lua_path
    io.stderr:write(string.format("[init] using static lua: %s\n", interpreter))
  end

  local extra_args = {}
  if arg then
    for i = 1, #arg do
      table.insert(extra_args, string.format("%q", arg[i]))
    end
  end

  local cmd = string.format(
    "LD_LIBRARY_PATH=%q DT_MCP_LD_REEXEC=1 %s %q %s",
    new_ld_path,
    interpreter or "lua",
    script,
    table.concat(extra_args, " ")
  )

  io.stderr:write(string.format(
    "[init] re-exec with LD_LIBRARY_PATH=%s (flatpak)\n",
    new_ld_path
  ))

  local exec_status = os.execute(cmd)
  local exit_code = 1

  if type(exec_status) == "number" then
    exit_code = exec_status
  elseif exec_status == true then
    exit_code = 0
  end

  os.exit(exit_code)
end

ensure_ld_library_path()

for _, p in ipairs(dt_paths.cpaths) do
  package.cpath = package.cpath .. ";" .. p
end

io.stderr:write(string.format(
  "[init] darktable prefix=%s source=%s lib=%s\n",
  tostring(dt_paths.prefix),
  tostring(dt_paths.source),
  tostring(dt_paths.lib_path)
))

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
local dt = require("darktable")(
  "--library",   os.getenv("HOME") .. "/.config/darktable/library.db",
  "--datadir",   dt_paths.datadir,
  "--moduledir", dt_paths.moduledir,
  "--configdir", os.getenv("HOME") .. "/.config/darktable",
  "--cachedir",  os.getenv("HOME") .. "/.cache/darktable"
)

local function select_darktable_cli()
  local override = os.getenv("DARKTABLE_CLI_CMD")
  if override and override ~= "" then
    return override, "env:DARKTABLE_CLI_CMD"
  end

  if command_exists("darktable-cli") then
    return "darktable-cli", "PATH"
  end

  if dt_paths.is_flatpak and command_exists("flatpak") then
    return "flatpak run --command=darktable-cli org.darktable.Darktable", "flatpak"
  end

  return nil, "missing"
end

local DARKTABLE_CLI_CMD, DARKTABLE_CLI_SOURCE = select_darktable_cli()

io.stderr:write(string.format(
  "[init] darktable-cli source=%s cmd=%s\n",
  tostring(DARKTABLE_CLI_SOURCE),
  tostring(DARKTABLE_CLI_CMD)
))

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

local function shell_escape(s)
  if not s then return "''" end
  -- POSIX single-quote escape: ' -> '\''
  return "'" .. tostring(s):gsub("'", "'\\''") .. "'"
end

local function run_command_capture(cmd)
  local handle = io.popen(cmd .. " 2>&1")
  if not handle then
    return false, -1, "io.popen failed", "popen"
  end

  local output = handle:read("*a") or ""
  local ok, reason, status = handle:close()

  local success = (type(ok) == "number" and ok == 0) or ok == true
  local exit_code = status
  if not exit_code or type(exit_code) ~= "number" then
    if type(ok) == "number" then
      exit_code = ok
    elseif ok == true then
      exit_code = 0
    else
      exit_code = -1
    end
  end

  return success, exit_code, output, reason
end

--------------------------------------------------
-- 4. Ferramentas MCP (lado darktable)
--------------------------------------------------

--------------------------------------------------
-- 4.1 list_collection
-- args: { min_rating?: number, only_raw?: boolean, collection_path?: string }
--------------------------------------------------
local function tool_list_collection(args)
  args = args or {}
  if args.min_rating ~= nil and type(args.min_rating) ~= "number" then
    return mcp_error("min_rating deve ser numérico", "invalid_min_rating", "min_rating")
  end

  if args.collection_path ~= nil and type(args.collection_path) ~= "string" then
    return mcp_error("collection_path deve ser string", "invalid_collection_path", "collection_path")
  end

  if args.only_raw ~= nil and type(args.only_raw) ~= "boolean" then
    return mcp_error("only_raw deve ser booleano", "invalid_only_raw", "only_raw")
  end

  local min_rating      = args.min_rating or -2
  local only_raw        = args.only_raw or false
  local collection_path = args.collection_path

  local result = {}

  for _, img in ipairs(dt.database) do
    local path_ok = true
    if collection_path and img.path then
      path_ok = img.path:find(collection_path, 1, true) ~= nil
    end

    if path_ok and (not only_raw or img.is_raw) and (img.rating or 0) >= min_rating then
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
-- 4.1b list_available_collections
-- args: {}
--------------------------------------------------
local function tool_list_available_collections(args)
  local groups = {}

  for _, img in ipairs(dt.database) do
    local path = img.path or ""
    local film = img.film and img.film.roll_name or nil

    if path ~= "" then
      if not groups[path] then
        groups[path] = { count = 0, film = film }
      end
      groups[path].count = groups[path].count + 1
    end
  end

  local result = {}
  for path, meta in pairs(groups) do
    table.insert(result, {
      path = path,
      film_roll = meta.film,
      image_count = meta.count
    })
  end

  table.sort(result, function(a, b)
    return a.path < b.path
  end)

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
  if args.path_contains ~= nil and type(args.path_contains) ~= "string" then
    return mcp_error("path_contains deve ser string", "invalid_path_contains", "path_contains")
  end

  if args.min_rating ~= nil and type(args.min_rating) ~= "number" then
    return mcp_error("min_rating deve ser numérico", "invalid_min_rating", "min_rating")
  end

  if args.only_raw ~= nil and type(args.only_raw) ~= "boolean" then
    return mcp_error("only_raw deve ser booleano", "invalid_only_raw", "only_raw")
  end

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
  if type(args.tag) ~= "string" or args.tag == "" then
    return mcp_error("tag é obrigatória e deve ser string", "invalid_tag", "tag")
  end

  if args.min_rating ~= nil and type(args.min_rating) ~= "number" then
    return mcp_error("min_rating deve ser numérico", "invalid_min_rating", "min_rating")
  end

  if args.only_raw ~= nil and type(args.only_raw) ~= "boolean" then
    return mcp_error("only_raw deve ser booleano", "invalid_only_raw", "only_raw")
  end

  local tag_name   = args.tag
  local min_rating = args.min_rating or -2
  local only_raw   = args.only_raw or false

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
      content = { { type = "text", text = "Parâmetro 'edits' (array) é obrigatório" } },
      isError = true
    }
  end

  for idx, e in ipairs(args.edits) do
    if type(e) ~= "table" or type(e.id) ~= "number" then
      return mcp_error("Cada edição precisa de 'id' numérico", "invalid_edit", "edits", { index = idx })
    end

    if e.rating ~= nil then
      if type(e.rating) ~= "number" then
        return mcp_error("rating deve ser numérico", "invalid_rating", "edits", { index = idx })
      end

      if e.rating < -1 or e.rating > 5 then
        return mcp_error("rating deve estar entre -1 e 5", "invalid_rating", "edits", { index = idx })
      end
    end
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
-- args: { edits: [ { id: number, color: string } ], overwrite?: boolean }
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
      content = { { type = "text", text = "Parâmetro 'edits' (array) é obrigatório" } },
      isError = true
    }
  end

  local overwrite = args.overwrite
  if overwrite ~= nil and type(overwrite) ~= "boolean" then
    return {
      content = { { type = "text", text = "overwrite deve ser booleano quando informado" } },
      isError = true
    }
  end

  for idx, e in ipairs(args.edits) do
    local color_idx = e and e.color and color_map[e.color]
    if type(e) ~= "table" or type(e.id) ~= "number" or color_idx == nil then
      return {
        content = { { type = "text", text = string.format("Cada edit precisa de 'id' numérico e 'color' válido (red, yellow, green, blue ou purple). Entrada inválida no índice %d", idx) } },
        isError = true
      }
    end
  end

  local updated = 0
  for _, e in ipairs(args.edits) do
    local img = dt.database[e.id]
    local idx = color_map[e.color]
    if img and idx ~= nil then
      if overwrite then
        for i = 0, 4 do
          img.colorlabels[i] = false
        end
      end
      img.colorlabels[idx] = true
      updated = updated + 1
    end
  end

  local mode = overwrite and "overwrite" or "append"
  return {
    content = {
      { type = "text", text = string.format("Applied colorlabels (%s) to %d images", mode, updated) }
    },
    isError = false
  }
end

--------------------------------------------------
-- 4.6 tag_batch
-- args: { tag: string, ids: [ number ] }
--------------------------------------------------
local function tool_tag_batch(args)
  if not args or type(args.tag) ~= "string" or args.tag == "" or type(args.ids) ~= "table" then
    return mcp_error("tag (string) e ids (array) são obrigatórios", "invalid_arguments", "tag")
  end

  for idx, id in ipairs(args.ids) do
    if type(id) ~= "number" then
      return mcp_error("ids deve conter apenas números", "invalid_id", "ids", { index = idx })
    end
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

  if not DARKTABLE_CLI_CMD then
    return {
      content = {
        {
          type = "text",
          text = "darktable-cli não encontrado (PATH ou flatpak); defina DARKTABLE_CLI_CMD para sobrescrever",
        }
      },
      isError = true
    }
  end

  if args.ids ~= nil then
    if type(args.ids) ~= "table" then
      return mcp_error("ids deve ser uma lista de números", "invalid_ids", "ids")
    end

    for idx, id in ipairs(args.ids) do
      if type(id) ~= "number" then
        return mcp_error("ids deve conter apenas números", "invalid_ids", "ids", { index = idx })
      end
    end
  end

  -- garantir que target_dir existe
  -- garantir que target_dir existe
  os.execute(string.format('mkdir -p %s', shell_escape(target_dir)))

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

    local skip = false
    if not overwrite then
      local f = io.open(out, "r")
      if f then
        f:close()
        -- pula se já existe
        skip = true
      end
    end

    if not skip then
      -- usar shell_escape para garantir que nomes com espaços ou caracteres especiais funcionem
      local cmd = string.format('%s %s %s', DARKTABLE_CLI_CMD, shell_escape(input), shell_escape(out))
      local success, exit_code, stderr_output, exit_reason = run_command_capture(cmd)

      if success then
        exported = exported + 1
      else
        table.insert(errors, {
          id = img.id,
          input = input,
          output = out,
          command = cmd,
          exit = exit_code,
          exit_reason = exit_reason,
          stderr = stderr_output,
        })
        io.stderr:write(string.format(
          "[export_collection] falha exportando id=%s exit=%s motivo=%s stderr=%s\n",
          tostring(img.id),
          tostring(exit_code),
          tostring(exit_reason),
          (stderr_output or ""):gsub("\n", " ")
        ))
      end
    end
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
      description = "Lista imagens da biblioteca com filtros simples (min_rating, only_raw, collection_path).",
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
          },
          collection_path = {
            type        = "string",
            description = "Filtra por um caminho de coleção (match direto em img.path)."
          }
        }
      }
    },
    {
      name        = "list_available_collections",
      title       = "Listar coleções disponíveis",
      description = "Retorna caminhos de coleção/folder conhecidos e o número de imagens em cada um.",
      inputSchema = {
        type = "object",
        properties = {}
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
          overwrite = {
            type        = "boolean",
            description = "Se true, limpa colorlabels anteriores antes de aplicar a nova cor. Padrão: false"
          },
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
  elseif name == "list_available_collections" then
    result = tool_list_available_collections(args)
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
