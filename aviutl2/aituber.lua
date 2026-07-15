--[[
AITuber連携スクリプト for AviUtl2
使い方:
  1. AIStreamerを起動: python server.py
  2. このスクリプトをAviUtl2のスクリプトエディタに貼り付けて実行

関数一覧:
  aituber.say("セリフ")         → 1行喋らせる（音声ファイル保存）
  aituber.run_script(lines)    → 台本を一気に喋らせる
  aituber.wait_say("セリフ")   → 喋り終わるまで待つ
]]

local aituber = {}
local BASE_URL = "http://localhost:8080"

-- HTTP POSTを送る内部関数
local function http_post(path, data)
    local json_str = '{"' .. table.concat(
        (function()
            local parts = {}
            for k, v in pairs(data) do
                if type(v) == "string" then
                    table.insert(parts, k .. '":"' .. v .. '"')
                elseif type(v) == "boolean" then
                    table.insert(parts, k .. '":' .. tostring(v))
                end
            end
            return parts
        end)(),
        ',"'
    ) .. '"}'

    -- AviUtl2のos.executeでcurlを呼ぶ
    local cmd = string.format(
        'curl -s -X POST "%s%s" -H "Content-Type: application/json" -d "%s"',
        BASE_URL, path, json_str:gsub('"', '\\"')
    )
    local result = os.execute(cmd)
    return result
end

-- 1行喋らせる
function aituber.say(text)
    http_post("/api/script/say", {text = text, wait = "false"})
end

-- 喋り終わるまで待つ
function aituber.wait_say(text)
    http_post("/api/script/say", {text = text, wait = "true"})
end

-- 台本を順番に喋らせる（テーブルで渡す）
function aituber.run_script(lines)
    for _, line in ipairs(lines) do
        if line ~= "" and not line:match("^#") then
            aituber.wait_say(line)
        end
    end
end

-- モードを切り替える
function aituber.set_mode(mode)
    os.execute(string.format('curl -s -X POST "%s/api/mode/%s"', BASE_URL, mode))
end

return aituber
