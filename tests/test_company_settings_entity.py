"""Company Setting page (/settings): Entity dropdown below Company Name in
the Add/Edit form, and an Entity column after Company Name in the table.
"""
import pathlib
import subprocess
import sys
import uuid

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)

ROOT = str(pathlib.Path(__file__).resolve().parent.parent)


def _run(src):
    r = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, cwd=ROOT, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"subprocess failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def _cleanup_company(name):
    _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.company import Company

async def main():
    async with AsyncSessionLocal() as db:
        for c in (await db.execute(select(Company).where(
                Company.company_name == "{name}"))).scalars().all():
            await db.delete(c)
        await db.commit()

asyncio.run(main())
""")


def test_settings_page_has_entity_dropdown_and_column(app_client, make_user):  # noqa: F811
    username, password = make_user("admin")
    _login(app_client, username, password)

    html = app_client.get("/settings", follow_redirects=True).text
    assert 'name="company_entity"' in html
    assert html.index('name="company_name"') < html.index('name="company_entity"')
    assert "<th>Entity</th>" in html
    assert html.index("<th>Company Name</th>") < html.index("<th>Entity</th>") < html.index("<th>GSTIN</th>")


def test_add_company_persists_entity_and_shows_in_table(app_client, make_user):  # noqa: F811
    suffix = uuid.uuid4().hex[:6]
    name = f"ITest Co {suffix}"
    try:
        username, password = make_user("admin")
        _login(app_client, username, password)
        csrf = app_client.cookies.get("csrf_token") or "dummy"

        r = app_client.post("/settings", data={
            "csrf_token": csrf, "company_id": "", "company_name": name,
            "company_entity": "OxyPC Computers",
        }, follow_redirects=False)
        assert r.status_code == 302, r.text[:300]

        html = app_client.get("/settings", follow_redirects=True).text
        row = html.split(name, 1)[1].split("</tr>", 1)[0]
        assert "OxyPC Computers" in row

        check = _run(f"""
import asyncio, sys
sys.path.insert(0, r"{ROOT}")
from sqlalchemy import select
from database import AsyncSessionLocal
from models.company import Company

async def main():
    async with AsyncSessionLocal() as db:
        c = (await db.execute(select(Company).where(Company.company_name == "{name}"))).scalar_one()
        print(c.company_entity)

asyncio.run(main())
""")
        assert check == "OxyPC Computers"
    finally:
        _cleanup_company(name)
