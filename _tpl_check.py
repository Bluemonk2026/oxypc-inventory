import sys
sys.path.insert(0, ".")
from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError

env = Environment(loader=FileSystemLoader("templates"))

for tpl in ["dealers/list.html", "telecalling/index.html"]:
    try:
        env.get_template(tpl)
        print(f"OK: {tpl}")
    except TemplateSyntaxError as e:
        print(f"SYNTAX ERROR in {tpl}: line {e.lineno}: {e.message}")
    except Exception as e:
        print(f"ERROR in {tpl}: {e}")
