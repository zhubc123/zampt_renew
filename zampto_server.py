import os
import signal
from DrissionPage import Chromium, ChromiumPage, ChromiumOptions
from DrissionPage.common import Settings
import asyncio
import logging
import random
import requests
from datetime import datetime
from time import sleep
from functools import wraps
import argparse
import socket
from urllib.parse import urlparse, parse_qs

def signal_handler(sig, frame):
    print("\n捕捉到 Ctrl+C，正在退出...")
    exit(1)

signal.signal(signal.SIGINT, signal_handler)

# 解析url中的id
def get_id_from_url(url):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    return query_params.get('id', [None])[0]

# 命令行参数
parser = argparse.ArgumentParser(description="-k 在脚本运行结束后不结束浏览器")
parser.add_argument('-k', '--keep', action='store_true', help='启用保留模式')
parser.add_argument('-d', '--debug', action='store_true', help='启用调试模式')
parser.add_argument('-r', '--retry', type=int, default=0, help='重试次数（整数）')
iargs = parser.parse_args()

# 浏览器路径候选
chrome_candidates = [
    "/usr/bin/chromium", "/usr/lib/chromium/chromium", "/usr/bin/chromium-browser",
    "/snap/bin/chromium", "/app/bin/chromium", "/opt/chromium/chrome",
    "/usr/local/bin/chromium", "/run/host/usr/bin/chromium",
    "/run/host/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/opt/google/chrome/chrome", "/run/host/usr/bin/microsoft-edge-stable"
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Mobile Safari/537.36",
]

chromepath = next((path for path in chrome_candidates if os.path.exists(path)), None)

# logging 配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
std_logger = logging.getLogger(__name__)

Settings.set_language('en')

# 环境变量
binpath = os.environ.get('CHROME_PATH', chromepath)
username = os.getenv("USERNAME")
password = os.getenv("PASSWORD")
tgbot_token = os.getenv("TG_TOKEN", "")
user_id = os.getenv("TG_USERID", "")

info = ""
login_deny = False

signurl = "https://auth.zampto.net/sign-in"
signurl_end = "auth.zampto.net/sign-in"
homeurl = "https://dash.zampto.net/homepage"
homeurlend = "/homepage"
overviewurl = "https://dash.zampto.net/overview"
overviewurl_end = "/overview"

def error_exit(msg):
    global std_logger, info
    std_logger.error(f"[ERROR] {msg}")
    info += f"[ERROR] {msg}\n"
    exit_process(1)

if not chromepath:
    error_exit("未找到可用的浏览器路径")

if not username or not password:
    error_exit("缺少 USERNAME 或 PASSWORD 环境变量")

if not tgbot_token or not user_id:
    std_logger.warning("TG_TOKEN 或 TG_USERID 未设置，通知功能不可用")

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def check_site_alive():
    try:
        r = requests.get("https://dash.zampto.net/", timeout=10)
        if r.status_code == 200:
            std_logger.info("网站似乎在线")
            return True
        else:
            std_logger.warning(f"网站返回 {r.status_code}，可能已下线或维护中")
            return False
    except Exception as e:
        std_logger.error(f"无法连接 zampto.net: {e} → 服务很可能已停止")
        return False

def exit_process(num=0):
    global info, tgbot_token, user_id
    if info.strip():
        info = f"ℹ️ Zampto 服务器续期通知\n用户：{username}\n{info}"
        if tgbot_token and user_id:
            tg_notifacation(info)
    if iargs.keep:
        std_logger.info("保留浏览器模式已启用")
    else:
        safe_close_browser()
    exit(num)

def safe_close_browser():
    global browser
    if 'browser' in globals() and browser:
        try:
            browser.quit()
            std_logger.info("浏览器已安全关闭")
        except:
            pass

def tg_notifacation(msg):
    if not tgbot_token or not user_id:
        return
    url = f"https://api.telegram.org/bot{tgbot_token}/sendMessage"
    payload = {"chat_id": user_id, "text": msg}
    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.json().get("ok"):
            std_logger.info("TG 通知发送成功")
        else:
            std_logger.error("TG 通知失败")
    except:
        pass

def capture_screenshot(file_name=None, save_dir='screenshots'):
    global page
    os.makedirs(save_dir, exist_ok=True)
    if not file_name:
        file_name = f"{username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    full_path = os.path.join(save_dir, file_name)
    try:
        page.get_screenshot(path=save_dir, name=file_name, full_page=True)
        std_logger.info(f"截图保存: {full_path}")
    except:
        std_logger.warning("截图失败")

def apply_stealth(page):
    js = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
    window.chrome = { runtime: {} };
    navigator.permissions.query = () => Promise.resolve({state: 'granted'});
    """
    page.run_js(js)
    std_logger.info("已应用 stealth 伪装")

def setup():
    global options, page, browser
    ua = get_random_user_agent()
    options = (
        ChromiumOptions()
        .incognito(True)
        .set_user_agent(ua)
        .set_argument('--no-sandbox')
        .set_argument('--disable-gpu')
        .set_argument('--window-size=1366,768')
        .set_argument('--disable-dev-shm-usage')
        .set_argument('--disable-blink-features=AutomationControlled')
        .set_argument('--disable-infobars')
        .set_argument('--no-first-run')
        .set_argument('--excludeSwitches=enable-automation')
        .set_argument('--disable-features=site-per-process')
        .set_browser_path(binpath)
    )
    
    if 'DISPLAY' not in os.environ:
        options.headless(True)
        options.set_argument('--headless=new')
    else:
        options.headless(False)
    
    browser = Chromium(options)
    page = browser.latest_tab
    apply_stealth(page)
    std_logger.info(f"浏览器启动完成，使用 UA: {ua}")

# ------------------ 页面操作函数 ------------------

def inputauth(inpage):
    u = inpage.ele('x://input[@autocomplete="username email"]', timeout=30)
    if u:
        u.clear(by_js=True)
        sleep(random.uniform(0.8, 1.5))
        u.input(username)
    p = inpage.ele('x://input[@type="password"]', timeout=30)
    if p:
        p.input(password)

def clickloginin(inpage):
    c = inpage.ele('x://button[@type="submit"]', timeout=30)
    if not c:
        error_exit("登录按钮未找到")
    inpage.scroll.to_see(c)
    sleep(random.uniform(0.6, 1.2))
    xof = random.randint(-20, 20)
    yof = random.randint(-10, 10)
    c.offset(x=xof, y=yof).click()
    std_logger.info(f"点击登录 (偏移 {xof},{yof})")

def click_if_cookie_option(tab):
    deny = tab.ele("x://button[contains(text(),'Do not consent') or contains(text(),'拒绝')]", timeout=10)
    if deny:
        deny.click()
        std_logger.info("已拒绝 Cookie 协议")

def renew_server(tab):
    renew_btn = tab.ele("x://a[contains(@onclick, 'handleServerRenewal') or contains(text(),'Renew')]", timeout=15)
    if renew_btn:
        tab.scroll.to_see(renew_btn)
        sleep(random.uniform(0.7, 1.3))
        renew_btn.click()
        std_logger.info("已点击 Renew 按钮")
    else:
        std_logger.warning("未找到 Renew 按钮")

def check_renew_result(tab):
    global info
    server_name_ele = tab.ele("x://span[contains(@class,'server-name') or contains(text(),'Server')]", timeout=15)
    if not server_name_ele:
        info += "❌ 未找到服务器名称，续期可能失败\n"
        return
    
    server_name = server_name_ele.text
    left_time = tab.ele('x://*[@id="nextRenewalTime" or contains(text(),"Next renewal")]', timeout=15)
    time_text = left_time.text if left_time else "未知"
    
    info += f"✅ 服务器 [{server_name}] 续期成功 | 剩余: {time_text}\n"
    std_logger.info(f"续期成功 - {server_name} | 剩余: {time_text}")

@require_browser_alive
async def open_server_tab():
    servers = page.eles("x://a[contains(@href, 'server?id=')]", timeout=20)
    if not servers:
        capture_screenshot("no_servers.png")
        error_exit("未找到任何服务器链接")
    
    for link in servers:
        url = link.attr('href')
        page.get(url, timeout=15)
        await wait_for(4, 8)
        renew_server(page)
        await wait_for(3, 6)
        check_renew_result(page)
        capture_screenshot(f"server_{get_id_from_url(url)}.png")
        await wait_for(5, 10)

@require_browser_alive
async def open_overview():
    if homeurlend in page.url:
        ov = page.ele('x://a[contains(text(),"Overview") or contains(@href,"overview")]', timeout=15)
        if ov:
            ov.click()
            await wait_for(5, 9)
    else:
        page.get(overviewurl, timeout=15)
    click_if_cookie_option(page)

@require_browser_alive
async def login():
    global login_deny
    if login_deny:
        page.get(signurl)
        login_deny = False
    inputauth(page)
    await wait_for(1, 3)
    clickloginin(page)
    await wait_for(8, 15)
    
    if signurl_end in page.url:
        login_deny = True
        error_exit("登录失败，请检查账号密码")
    else:
        std_logger.info("登录成功")
        # 额外验证
        if "dashboard" not in page.url and "overview" not in page.url:
            error_exit("登录后未到达预期页面，可能被拦截")

@require_browser_alive
async def open_web():
    if not page.url.startswith(signurl):
        page.get(signurl, timeout=15)
    await wait_for(6, 12)

# ------------------ 主流程 ------------------

steps = [
    {"match": "/newtab/", "action": open_web, "name": "打开登录页"},
    {"match": signurl_end, "action": login, "name": "登录"},
    {"match": homeurlend, "action": open_overview, "name": "进入 Overview"},
    {"match": overviewurl_end, "action": open_server_tab, "name": "处理服务器续期"},
]

async def continue_execution():
    current_url = page.url
    std_logger.info(f"当前 URL: {current_url}")
    
    start_index = 0
    for i, step in enumerate(steps):
        if step["match"] in current_url:
            start_index = i
            break
    
    for i in range(start_index, len(steps)):
        step = steps[i]
        std_logger.info(f"执行步骤: {step['name']}")
        action = step["action"]
        try:
            await action()
            capture_screenshot(f"{step['name']}_{i}.png")
            await wait_for(4, 10)
        except Exception as e:
            std_logger.error(f"步骤 {step['name']} 失败: {e}")
            capture_screenshot(f"error_{step['name']}.png")
            error_exit(str(e))
    std_logger.info("所有步骤完成")
    return 0

async def wait_for(a, b):
    t = random.uniform(a, b)
    std_logger.debug(f"等待 {t:.2f} 秒")
    await asyncio.sleep(t)

def require_browser_alive(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        global browser, page
        if browser.tabs_count == 0:
            error_exit("浏览器标签页已崩溃")
        page = browser.latest_tab
        return await func(*args, **kwargs)
    return wrapper

async def main():
    if not check_site_alive():
        info = "zampto.net 似乎已不可访问（503 或连接失败），续期无意义。"
        exit_process(1)
    
    setup()
    try:
        await continue_execution()
    except Exception as e:
        std_logger.error(f"主流程异常: {e}")
        return 1
    return 0

if __name__ == "__main__":
    exit_code = 0
    if iargs.retry > 0:
        for attempt in range(1, iargs.retry + 1):
            info += f"第 {attempt}/{iargs.retry} 次尝试\n"
            success = asyncio.run(main())
            if success == 0:
                break
            if attempt < iargs.retry:
                sleep(30)  # 重试间隔
    else:
        success = asyncio.run(main())
    
    exit_process(success)
