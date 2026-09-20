# -*- coding: utf-8 -*-
"""邮箱渠道客户端子包：Emailnator 官方内部 API 逆向客户端（原 temp/channel_mail 外挂模块收编）。
对外导出 generate_email / EmailnatorClient，供 mail_backend 使用。"""
from .email_api import generate_email  # noqa: F401
from .emailnator_client import EmailnatorClient  # noqa: F401

__all__ = ["generate_email", "EmailnatorClient"]
