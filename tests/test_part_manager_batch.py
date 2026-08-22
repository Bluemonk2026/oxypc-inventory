"""Part Manager page batch: Consumed tile, the new Parts Consumption tab,
Upload New/Harvest sample-file modals, and the trimmed Add Harvest modal.
"""
import pytest

from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def _get_spare_parts(app_client, make_user):
    username, password = make_user("spare_parts_manager")
    _login(app_client, username, password)
    return app_client.get("/spare-parts", follow_redirects=True).text


def test_consumed_tile_is_not_scoped_to_this_month(app_client, make_user):  # noqa: F811
    html = _get_spare_parts(app_client, make_user)
    assert "Consumed This Month" not in html
    assert ">Consumed<" in html


def test_parts_consumption_tab_present_with_search_and_export(app_client, make_user):  # noqa: F811
    html = _get_spare_parts(app_client, make_user)
    assert 'id="partsConsumptionTab"' in html
    assert 'id="parts-consumption-tab"' in html
    assert "Total Parts Changed" in html
    assert "Total Parts Amount" in html
    assert 'id="pcSearch"' in html
    assert "pcFilter()" in html


def test_download_sample_moved_into_upload_modals(app_client, make_user):  # noqa: F811
    html = _get_spare_parts(app_client, make_user)
    master_tab = html.split('id="masterTab"', 1)[1].split('<!-- ── TAB 3', 1)[0]
    assert "Download Sample" not in master_tab
    new_modal = html.split('id="uploadNewModal"', 1)[1].split("</form>", 1)[0]
    harvest_modal = html.split('id="uploadHarvestModal"', 1)[1].split("</form>", 1)[0]
    for modal in (new_modal, harvest_modal):
        assert "/spare-parts/bulk-template" in modal
        assert 'enctype="multipart/form-data"' in modal


def test_add_harvest_modal_trimmed_and_reordered(app_client, make_user):  # noqa: F811
    html = _get_spare_parts(app_client, make_user)
    modal = html.split('id="harvestModal"', 1)[1].split("</form>", 1)[0]
    assert 'name="main_category"' not in modal
    assert 'name="invoice_ref"' not in modal
    assert 'id="hv_inv_qty"' not in modal
    assert modal.index('name="category"') < modal.index('name="part_brand"')


def test_export_delete_selected_start_hidden(app_client, make_user):  # noqa: F811
    html = _get_spare_parts(app_client, make_user)
    assert 'id="expSel_partsTable" class="btn btn-outline-info btn-sm d-none"' in html
    assert 'id="delSel_partsTable" class="btn btn-outline-danger btn-sm d-none"' in html
