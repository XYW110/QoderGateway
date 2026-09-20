# -*- coding: utf-8 -*-
"""定位/修复验证：#basic_password 填不进去的问题。

流程：开浏览器 → 注册页 → 填姓名/邮箱 → 提交 → 等密码框 → 用新 _fill 填 → 打印诊断。
不提交密码、不完成注册。
"""
import sys
import time

sys.path.insert(0, "src")

from qoder2api.registrar import RegistrarBot, REGISTER_URL, _log


def dump_pw_field(bot: RegistrarBot, tag: str) -> None:
    js = """
    (function(){
      var out = [];
      document.querySelectorAll('input').forEach(function(e){
        var r = e.getBoundingClientRect();
        var cs = getComputedStyle(e);
        out.push({id: e.id, name: e.name, type: e.type,
                  displayed: r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none',
                  disabled: e.disabled, value: e.value, maxlength: e.maxLength});
      });
      return JSON.stringify(out);
    })()
    """
    raw = bot.page.run_js(js)
    print(f"--- {tag} inputs ---")
    import json
    try:
        for item in json.loads(raw or "[]"):
            print("   ", item)
    except Exception:
        print("   raw:", raw)


def main() -> None:
    bot = RegistrarBot(task_id="pwtest", cleanup_profile=True)
    try:
        bot._open_hidden(REGISTER_URL)
        bot._locate("#basic_firstName", timeout=60, displayed=True, desc="注册页姓输入框")
        print("page loaded")

        bot._fill("#basic_firstName", "Test", must_id="basic_firstName")
        bot._fill("#basic_lastName", "User", must_id="basic_lastName")
        bot._fill("#basic_email", f"pwtest{int(time.time())}@mailinator.com", must_id="basic_email")
        print("name/email filled OK")

        bot._click_submit()
        print("submitted email step")

        bot._locate("#basic_password", timeout=60, displayed=True, desc="密码输入框")
        print("password field located")
        dump_pw_field(bot, "before fill")

        t0 = time.time()
        try:
            bot._fill("#basic_password", "AzOz0X)@7=qd", must_id="basic_password")
            print(f"PASSWORD FILL OK in {time.time()-t0:.1f}s")
        except Exception as e:
            print(f"PASSWORD FILL FAILED: {e}")

        dump_pw_field(bot, "after fill")
    finally:
        bot.close()
        print("closed")


if __name__ == "__main__":
    main()
