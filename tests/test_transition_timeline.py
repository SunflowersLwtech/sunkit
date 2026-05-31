from __future__ import annotations

import unittest


def compute_scene_frames(total: int, weights: list[float]) -> list[int]:
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise ValueError("weights must be positive")
    raw = [(weight / weight_sum) * total for weight in weights]
    floored = [int(value // 1) for value in raw]
    remainder = total - sum(floored)
    order = sorted(
        [{"index": index, "frac": value - int(value // 1)} for index, value in enumerate(raw)],
        key=lambda item: item["frac"],
        reverse=True,
    )
    cursor = 0
    while remainder > 0:
        floored[order[cursor % len(order)]["index"]] += 1
        cursor += 1
        remainder -= 1
    return [max(1, frame_count) for frame_count in floored]


def choose_transition_frames(duration: int, weights: list[float], fps: int) -> int:
    count = len(weights)
    if count < 2:
        return 0
    transitions = count - 1
    min_dwell = max(8, round(fps * 0.45))
    ideal = min(12, max(5, round(fps * 0.3)))
    for transition in range(ideal, 3, -1):
        frames = compute_scene_frames(duration + transitions * transition, weights)
        min_visible = min(
            frame_count
            - (transition if index > 0 else 0)
            - (transition if index < count - 1 else 0)
            for index, frame_count in enumerate(frames)
        )
        acc = 0
        mid = duration / 2
        mid_inside_transition = False
        for frame_count in frames[:-1]:
            start = acc + frame_count - transition
            end = acc + frame_count
            if start <= mid <= end:
                mid_inside_transition = True
                break
            acc += frame_count - transition
        if min_visible >= min_dwell and not mid_inside_transition:
            return transition
    return 0


def scene_boundaries(frames: list[int], transition: int) -> list[int]:
    starts: list[int] = []
    acc = 0
    for index, frame_count in enumerate(frames):
        starts.append(acc)
        acc += frame_count - (transition if index < len(frames) - 1 else 0)
    return starts


class TransitionTimelineTests(unittest.TestCase):
    def test_transition_series_consumes_exact_duration(self) -> None:
        duration = 360
        fps = 30
        for scene_count in range(1, 7):
            weights = [1 / scene_count] * scene_count
            transition = choose_transition_frames(duration, weights, fps)
            frames = compute_scene_frames(duration + max(0, scene_count - 1) * transition, weights)
            consumed = sum(frames) - max(0, scene_count - 1) * transition
            self.assertEqual(consumed, duration)
            self.assertEqual(scene_boundaries(frames, transition)[0], 0)

    def test_transition_choice_keeps_midpoint_out_of_crossfade(self) -> None:
        duration = 360
        fps = 30
        weights = [0.25, 0.25, 0.25, 0.25]
        transition = choose_transition_frames(duration, weights, fps)

        self.assertEqual(transition, 0)

        weights = [0.2, 0.18, 0.15, 0.15, 0.15, 0.17]
        transition = choose_transition_frames(duration, weights, fps)
        frames = compute_scene_frames(duration + (len(weights) - 1) * transition, weights)
        mid = duration / 2
        acc = 0
        for frame_count in frames[:-1]:
            self.assertFalse(acc + frame_count - transition <= mid <= acc + frame_count)
            acc += frame_count - transition


if __name__ == "__main__":
    unittest.main()
