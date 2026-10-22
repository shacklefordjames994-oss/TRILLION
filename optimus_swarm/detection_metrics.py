from dataclasses import dataclass
from typing import Sequence

from optimus_swarm.rgbd_perception import Detection2D


@dataclass(frozen=True)
class DetectionReport:
    status: str
    iou_threshold: float
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    mean_matched_iou: float | None


def box_iou(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    intersection_w = max(0, min(ax2, bx2) - max(ax1, bx1))
    intersection_h = max(0, min(ay2, by2) - max(ay1, by1))
    intersection = intersection_w * intersection_h

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - intersection

    return intersection / union if union > 0 else 0.0


def evaluate_detections(
    predictions: Sequence[Detection2D],
    ground_truth: Sequence[Detection2D],
    iou_threshold: float = 0.5,
) -> DetectionReport:
    """
    Greedy one-to-one matching by descending IoU.

    Match candidates must have the same class and IoU >= threshold.
    Use independent ground-truth boxes; do not reuse model predictions
    as ground truth in a real detector benchmark.
    """
    if not 0.0 < iou_threshold <= 1.0:
        raise ValueError("iou_threshold must be in (0, 1]")

    candidates = []

    for pi, pred in enumerate(predictions):
        for gi, truth in enumerate(ground_truth):
            if pred.class_name != truth.class_name:
                continue

            overlap = box_iou(pred.bbox_xyxy, truth.bbox_xyxy)
            if overlap >= iou_threshold:
                candidates.append((overlap, pi, gi))

    candidates.sort(reverse=True)

    used_predictions = set()
    used_truth = set()
    matched_ious = []

    for overlap, pi, gi in candidates:
        if pi in used_predictions or gi in used_truth:
            continue

        used_predictions.add(pi)
        used_truth.add(gi)
        matched_ious.append(overlap)

    tp = len(used_predictions)
    fp = len(predictions) - tp
    fn = len(ground_truth) - len(used_truth)

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    return DetectionReport(
        status="EVALUATED",
        iou_threshold=iou_threshold,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        mean_matched_iou=sum(matched_ious) / len(matched_ious) if matched_ious else None,
    )
