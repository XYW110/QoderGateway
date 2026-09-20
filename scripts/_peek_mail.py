# -*- coding: utf-8 -*-
from pathlib import Path
import re

p = sorted(Path(r"D:\Work\Project\TestProject\QoderGateway\logs\mail").glob("*.txt"),
           key=lambda x: x.stat().st_mtime)[-1]
print("FILE", p.name, "LEN", p.stat().st_size)
t = p.read_text(encoding="utf-8", errors="replace")
body = t.split("----- body -----", 1)[-1]
plain = re.sub(r"(?is)<style.*?</style>", " ", body)
plain = re.sub(r"(?is)<script.*?</script>", " ", plain)
plain = re.sub(r"(?i)style=\"[^\"]*\"", " ", plain)
plain = re.sub(r"(?i)style='[^']*'", " ", plain)
plain = re.sub(r"<[^>]+>", " ", plain)
plain = re.sub(r"&\w+;", " ", plain)
plain = re.sub(r"\s+", " ", plain)
print("PLAIN:", plain[:2000])
print("6DIGIT", re.findall(r"(?<!\d)\d{6}(?!\d)", plain))
print("NEAR:")
for m in re.finditer(r".{0,50}(?:code|verify|otp|验证码|Qoder).{0,50}", plain, re.I):
    print(" ", m.group(0))
