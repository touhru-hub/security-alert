#!/usr/bin/env python3
"""
基金行情监控推送脚本
支持多只基金代码配置，通过 PushPlus 推送到个人微信
"""
import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
PUSHPLUS_URL = "http://www.pushplus.plus/send"

def load_config():
    """加载配置文件，文件不存在时返回空字典"""
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def get_fund_codes():
    """获取基金代码列表，优先读取环境变量 FUND_CODES（逗号分隔），回退到 config.json"""
    env_codes = os.environ.get("FUND_CODES", "").strip()
    if env_codes:
        return [c.strip() for c in env_codes.split(",") if c.strip()]
    cfg = load_config()
    funds = cfg.get("funds", [])
    if not funds:
        raise RuntimeError(
            "未配置基金代码，请设置环境变量 FUND_CODES（逗号分隔），或在 config.json 中添加 funds 数组"
        )
    return [str(c).strip() for c in funds]

def get_pushplus_token():
    """获取 PushPlus Token，优先读取环境变量，回退到 config.json"""
    cfg = load_config()
    token = cfg.get("pushplus_token", "").strip() or os.environ.get("PUSHPLUS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("PushPlus Token 未配置，请设置 PUSHPLUS_TOKEN 环境变量或在 config.json 填写 pushplus_token")
    return token

def fetch_fund_estimate(code: str):
    """
    获取基金估算净值
    数据源：天天基金 https://fundgz.1234567.com.cn
    参数：基金代码，如 014611
    返回：dict 包含 fundcode, name, gsz, gszzl, gztime, dwjz, jzrq 等
    """
    url = f"https://fundgz.1234567.com.cn/js/{code}.js"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as response:
        text = response.read().decode("utf-8").strip()

    # 解析 jsonpgz({...});
    match = re.match(r"jsonpgz\((.*)\);?$", text, re.S)
    if not match:
        raise ValueError(f"基金代码 {code} 接口返回格式异常")

    data = json.loads(match.group(1))

    # 校验必要字段
    required = ["fundcode", "name", "gsz", "gszzl", "gztime", "dwjz", "jzrq"]
    for field in required:
        if field not in data or data[field] is None:
            raise ValueError(f"基金代码 {code} 缺少必要字段: {field}")

    return data

def format_fund_msg(data: dict):
    """格式化基金消息（Markdown 简洁版）"""
    gzzl = float(data.get("gszzl", "0") or "0")
    symbol = "+" if gzzl >= 0 else ""
    emoji = "🔴" if gzzl >= 0 else "🟢"

    lines = [
        f"{emoji} {data['fundcode']} {data['name']}",
        f"估算净值: {data['gsz']} ({symbol}{gzzl}%)",
        f"前日净值: {data['dwjz']} ({data['jzrq']})",
        f"估值时间: {data['gztime']}",
    ]
    return "\n".join(lines)

def push_wechat(title: str, content: str):
    """调用 PushPlus API 推送消息到微信"""
    token = get_pushplus_token()
    if not token:
        raise RuntimeError("PushPlus Token 未配置，请设置环境变量 PUSHPLUS_TOKEN")

    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": "txt",  # txt, html, json, markdown
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        PUSHPLUS_URL,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    return result

def main():
    funds = get_fund_codes()
    if not funds:
        print("⚠️ 未配置基金代码。请在环境变量 FUND_CODES 中设置，格式: FUND_CODES=014611,161903,006533,320007")
        return

    print(f"📊 开始监控 {len(funds)} 只基金...")
    print(f"⏰ 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    success_items = []
    failed_items = []

    for code in funds:
        code = str(code).strip()
        try:
            data = fetch_fund_estimate(code)
            success_items.append(data)
            print(f"  ✅ {code} {data['name']} 估值: {data['gsz']} ({data['gszzl']}%)")
        except Exception as e:
            failed_items.append((code, str(e)))
            print(f"  ❌ {code} 获取失败: {e}")

    if not success_items:
        print("\n⚠️ 所有基金获取失败，请检查网络或基金代码是否正确。")
        return

    # 拼接推送消息
    title_parts = [f"📊 {x['name']} {x['gszzl']}%" for x in success_items]
    title = " ".join(title_parts) if title_parts else "基金行情"

    content_parts = [format_fund_msg(x) for x in success_items]
    if failed_items:
        content_parts.append("\n❌ 获取失败：")
        for code, err in failed_items:
            content_parts.append(f"- {code}: {err}")

    content = "\n\n".join(content_parts)

    print("\n正在推送到微信...")
    result = push_wechat(title, content)

    # 输出推送结果
    print(f"\n推送结果:")
    print(f"  状态码: {result.get('code')}")
    print(f"  消息: {result.get('msg')}")

    if result.get("code") == 200:
        print("✅ 推送成功！请查看微信通知。")
    elif result.get("code") == 903:
        print("⚠️ Token 无效或未绑定微信，请确认：")
        print("  1. PushPlus 已注册并绑定微信号")
        print("  2. Token 正确填写在 config.json 或环境变量 PUSHPLUS_TOKEN")
    else:
        print(f"❌ 推送失败: {result.get('msg')}")

if __name__ == "__main__":
    main()
