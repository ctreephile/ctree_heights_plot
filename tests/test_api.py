"""
API endpoint tests for backend.main.
"""

from __future__ import annotations

from backend.main import (
    ComputeRequest,
    CrystalGrowthRequest,
    ExportRequest,
    LoopTreeRequest,
    NodeDetailsRequest,
    P4HeatmapAddNextRequest,
    ValidateRequest,
    api_compute,
    api_crystal_growth,
    api_crystal_growth_gif,
    api_export,
    api_loop_tree,
    api_node_details,
    api_p4_heatmap,
    api_p4_heatmap_add_next,
    api_validate,
    get_presets,
    health_check,
)


def test_health_and_presets():
    h = health_check()
    assert h["status"] == "ok"

    presets = get_presets()
    assert len(presets) >= 4
    assert presets[0]["p"] == 3


def test_api_validate_and_compute():
    v = api_validate(ValidateRequest(p=4, q=[None, 2, 1]))
    assert v["valid"] is True
    assert v["strictly_divisible"] is True

    c = api_compute(ComputeRequest(p=3, q=[None, 5], n_start=1, n_end=500, max_steps=5000))
    assert c["p"] == 3
    assert len(c["points"]["n"]) == 500
    assert len(c["loops"]) >= 5


def test_api_node_details_and_export():
    nd = api_node_details(
        NodeDetailsRequest(
            p=3,
            q=[None, 1],
            target_n=16,
            n_start=1,
            n_end=100,
            max_steps=5000,
        )
    )
    assert nd["target"]["n"] == 16
    assert nd["algorithmic_neighbors"]["immediate_forward"]["n"] == 8
    preds = [x["n"] for x in nd["algorithmic_neighbors"]["predecessors_step1"]]
    assert preds == [32, 5]

    resp_png = api_export(
        ExportRequest(
            p=3,
            q=[None, 5],
            n_start=1,
            n_end=200,
            format="png",
        )
    )
    assert resp_png.media_type == "image/png"
    assert resp_png.body[:8] == b"\x89PNG\r\n\x1a\n"


def test_api_loop_tree():
    # 1. Full loop mode for 3n+5 loop_id=1 ([1, 8, 4, 2]) up to height 10
    res_loop = api_loop_tree(
        LoopTreeRequest(
            p=3,
            q=[None, 5],
            loop_id=1,
            max_height=10,
            root_mode="loop",
        )
    )
    assert res_loop["root_mode"] == "loop"
    assert res_loop["max_height"] == 10
    assert res_loop["loop"]["elements"] == [1, 8, 4, 2]
    assert len(res_loop["loop"]["elements_detail"]) == 4
    assert res_loop["total_nodes"] > 10
    assert len(res_loop["tree"]["children"]) == 4

    # 2. Single root number mode starting from n=16 up to height 5
    res_single = api_loop_tree(
        LoopTreeRequest(
            p=3,
            q=[None, 5],
            loop_id=1,
            max_height=5,
            root_mode="single",
            root_n=16,
        )
    )
    assert res_single["root_mode"] == "single"
    assert res_single["tree"]["n"] == 16
    assert res_single["total_nodes"] >= 6


def test_api_crystal_growth_and_gif():
    req = CrystalGrowthRequest(
        p=3,
        q=[None, 1],
        loop_id=1,
        max_height=5,
        max_gen=3,
        base_multiplier=3,
        layout_mode="radial",
    )
    res = api_crystal_growth(req)
    assert res["p"] == 3
    assert len(res["generations"]) == 4
    # Verify Fibonacci saturation progression [3, 2, 3, 4, 7, 11]
    assert res["generations"][2]["spectrum"] == [3, 2, 3, 4, 7, 11]
    assert res["generations"][3]["spectrum"] == [3, 2, 3, 4, 7, 11]
    assert res["generations"][3]["frozen_height"] == 5

    gif_resp = api_crystal_growth_gif(req)
    assert gif_resp.media_type == "image/gif"
    assert gif_resp.body[:6] in (b"GIF87a", b"GIF89a")


def test_api_p4_heatmap_and_add_next():
    hm = api_p4_heatmap(max_height=10, grid_size=30)
    assert len(hm["q1_vals"]) == 30
    assert len(hm["q2_vals"]) == 30
    assert len(hm["cells"]) == 900
    assert hm["cells"]["8,88"]["nodes"] == 43569
    assert hm["cells"]["8,88"]["base_str"] == "(11,1)"
    assert "(11,1)" in hm["families"]

    hm80 = api_p4_heatmap(max_height=10, grid_size=80)
    assert len(hm80["q1_vals"]) == 80
    assert len(hm80["q2_vals"]) == 80
    assert len(hm80["cells"]) == 6400
    assert 80 in hm80["available_grids"]
    assert hm80["cells"]["185,115"]["base_str"] == "(23,37)"
    assert hm80["cells"]["185,115"]["nodes"] == 6915

    existing = [[c["q1"], c["q2"]] for c in hm["cells"].values()]
    added = api_p4_heatmap_add_next(
        P4HeatmapAddNextRequest(
            base_q1=11,
            base_q2=1,
            existing_qs=existing,
            max_height=10,
        )
    )
    # Next after g=1,2,4,5,7,8 for (11,1) is g=10 -> (110, 10)
    assert added["g"] == 10
    assert added["cell"]["q1"] == 110
    assert added["cell"]["q2"] == 10
    assert added["cell"]["base_str"] == "(11,1)"
    assert added["cell"]["nodes"] > 0




