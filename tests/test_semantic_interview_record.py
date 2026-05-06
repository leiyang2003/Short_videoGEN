import sys
import unittest
from argparse import Namespace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import novel2video_plan as n2v  # noqa: E402
import generate_keyframes_atlas_i2i as keyframes  # noqa: E402
import run_seedance_test as seedance  # noqa: E402


def base_shot() -> n2v.ShotPlan:
    return n2v.ShotPlan(
        shot_id="SH11",
        priority="P0",
        intent="旧摘要误把门外写粗",
        duration_sec=5,
        shot_type="中景",
        movement="固定机位",
        framing_focus="银座高级酒店门外，美咲神情紧张",
        action_intent="美咲在酒店门外听到消息",
        emotion_intent="惊惧克制",
        scene_id="EP02_HOTEL",
        scene_name="银座高级酒店门外",
        dialogue=[{"speaker": "石川刑警", "text": "电话里说彩花死了。", "source": "phone"}],
        narration=[],
        subtitle=["电话里说彩花死了。"],
        positive_core="银座高级酒店门外，美咲听到彩花尸体的消息",
        source_basis="门内传来石川刑警的声音，提到彩花尸体上的丝巾勒痕。",
        first_frame_contract={
            "location": "银座高级酒店门外",
            "visible_characters": ["佐藤美咲", "佐藤彩花"],
            "speaking_state": "美咲惊讶说话",
        },
        i2v_contract={"phone_contract": {"holder": "佐藤美咲"}},
    )


def sh11_interview() -> dict:
    return {
        "shot_id": "EP02_SH11",
        "q1_people_count_and_visibility": {
            "people": [
                {"name": "佐藤美咲", "visibility": "onscreen_visible", "evidence": "美咲靠墙偷听"},
                {"name": "石川刑警", "visibility": "offscreen_voice", "evidence": "门内传来石川的声音"},
                {"name": "佐藤彩花尸体", "visibility": "mentioned_only", "evidence": "提到尸体"},
                {"name": "小樱", "visibility": "mentioned_only", "evidence": "提到小樱"},
            ],
        },
        "q2_onscreen_people_location_and_action": {
            "visual_location": "高档酒店套房/彩花案发房间的关闭房门外，走廊门边墙侧",
            "spatial_relations": "美咲在关闭房门外，石川刑警的声音从门内案发套房传出，不是电话。",
            "onscreen_people": [
                {
                    "name": "佐藤美咲",
                    "position": "走廊门边墙侧",
                    "first_frame_action": "紧握手袋靠墙偷听",
                    "speaking_or_mouth_state": "沉默无口型",
                }
            ],
            "first_frame_ground_truth": "美咲在彩花案发套房关闭房门外靠墙偷听，沉默无口型。",
        },
        "q3_narration": {"has_narration": False, "narration_text": "", "narration_source": "none"},
        "q4_dialogue": {
            "dialogue_lines": [
                {
                    "speaker": "石川刑警",
                    "listener": "佐藤美咲",
                    "text": "彩花的尸体上有丝巾勒痕。",
                    "text_status": "adapted_from_summary",
                    "source_quote": "提到彩花尸体上的丝巾勒痕",
                    "source": "offscreen_local",
                    "voice_origin": "门内案发套房",
                    "speaker_visible": False,
                    "listener_visible": True,
                    "lip_sync_target": "none",
                }
            ],
            "onscreen_character_speaks": False,
            "audio_ground_truth": "石川刑警声音从门内案发套房传出，不是电话，不是旁白。",
        },
        "props_and_objects": {
            "visible_props": [{"prop": "手袋", "visibility": "visible", "position": "美咲手中"}],
            "mentioned_only_objects": [{"object": "丝巾勒痕", "should_be_visible": False}],
        },
        "semantic_risks": [],
        "record_ready_contract": {
            "positive_intent_contract": "美咲在案发套房关闭房门外走廊靠墙偷听，紧握手袋，沉默无口型；门内传出石川刑警声音。",
            "location_for_record": "高档酒店套房/彩花案发房间的关闭房门外，走廊门边墙侧",
            "visible_characters_for_record": ["佐藤美咲"],
            "offscreen_characters_for_record": ["石川刑警"],
            "mentioned_only_people_for_record": ["佐藤彩花尸体", "小樱"],
            "dialogue_for_record": [],
            "death_visual_target_visible": None,
            "should_apply_death_state_to_visible_character": False,
        },
        "evidence_quotes": ["门内传来石川刑警的声音"],
    }


class SemanticInterviewRecordTests(unittest.TestCase):
    def test_interview_overrides_conflicting_record_fields(self) -> None:
        shot = n2v.apply_semantic_interview_to_shot(base_shot(), sh11_interview())
        first = shot.first_frame_contract or {}
        self.assertEqual(first["location"], "高档酒店套房/彩花案发房间的关闭房门外，走廊门边墙侧")
        self.assertEqual(first["visible_characters"], ["佐藤美咲"])
        self.assertEqual(first["speaking_state"], "佐藤美咲沉默无口型")
        self.assertEqual(first["key_props"], ["手袋"])
        self.assertEqual(shot.dialogue[0]["source"], "offscreen")
        self.assertEqual(shot.dialogue[0]["text_status"], "adapted_from_summary")
        self.assertEqual((shot.i2v_contract or {}).get("phone_contract"), {})
        self.assertEqual((shot.dialogue_blocking or {}).get("lip_sync_policy"), "offscreen_local_voice_listener_silent")
        self.assertFalse(shot.semantic_ground_truth["should_apply_death_state_to_visible_character"])

    def test_interview_refines_bad_door_location_contract(self) -> None:
        interview = sh11_interview()
        interview["q2_onscreen_people_location_and_action"]["visual_location"] = "银座高级酒店门外，靠墙位置，面对封锁的酒店入口门"
        interview["record_ready_contract"]["location_for_record"] = "银座高级酒店门外至门内"
        shot = n2v.apply_semantic_interview_to_shot(base_shot(), interview)
        self.assertEqual(
            (shot.first_frame_contract or {})["location"],
            "银座高级酒店彩花案发套房关闭房门外，走廊门边墙侧",
        )
        self.assertNotIn("推门", shot.positive_core)

    def test_build_record_persists_semantic_ground_truth(self) -> None:
        shot = n2v.apply_semantic_interview_to_shot(base_shot(), sh11_interview())
        episode = n2v.EpisodePlan(
            episode_id="EP02",
            episode_number=2,
            episode_label="第2集",
            title="测试",
            goal="",
            conflict="",
            emotions=[],
            hook="",
            source_basis=[],
            story_function="",
        )
        characters = [
            n2v.Character("MISAKI_FEMALE", "MISAKI", "佐藤美咲", "二十多岁女性", [], []),
            n2v.Character("ISHIKAWA_DETECTIVE", "ISHIKAWA", "石川刑警", "刑警男性", [], []),
        ]
        record = n2v.build_record(
            "GinzaNight_EP02",
            episode,
            "douyin",
            "现代东京银座",
            [],
            n2v.DEFAULT_LANGUAGE_POLICY,
            "门内传来石川刑警的声音，提到彩花尸体上的丝巾勒痕。",
            characters,
            shot,
            "exp_test",
        )
        self.assertEqual(record["first_frame_contract"]["visible_characters"], ["佐藤美咲"])
        self.assertEqual(record["dialogue_language"]["dialogue_lines"][0]["text_status"], "adapted_from_summary")
        self.assertEqual(record["semantic_ground_truth"]["mentioned_only_people"], ["佐藤彩花尸体", "小樱"])

    def test_no_semantic_interview_flag_restores_debug_path(self) -> None:
        self.assertFalse(n2v.should_run_semantic_interview(Namespace(backend="llm", no_semantic_interview=True)))
        self.assertTrue(n2v.should_run_semantic_interview(Namespace(backend="llm", no_semantic_interview=False)))
        self.assertFalse(n2v.should_run_semantic_interview(Namespace(backend="heuristic", no_semantic_interview=False)))

    def test_mentioned_only_corpse_does_not_create_visible_death_contract(self) -> None:
        record = {
            "prompt_render": {"shot_positive_core": "门内对白提到彩花尸体上的丝巾勒痕。"},
            "semantic_ground_truth": {
                "death_visual_target_visible": None,
                "should_apply_death_state_to_visible_character": False,
                "record_ready_contract": {
                    "death_visual_target_visible": None,
                    "should_apply_death_state_to_visible_character": False,
                },
            },
        }
        self.assertFalse(keyframes.record_requires_death_state_contract(record))
        self.assertFalse(seedance.record_requires_death_state_contract(record))

    def test_unambiguous_action_shot_is_unchanged_without_interview(self) -> None:
        shot = base_shot()
        self.assertEqual(n2v.apply_semantic_interview_to_shot(shot, {}), shot)


if __name__ == "__main__":
    unittest.main()
