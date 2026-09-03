import numpy as np


def face_descriptor(gray_face):
    image = np.asarray(gray_face, dtype=np.float32)
    if image.ndim != 2 or min(image.shape) < 24:
        raise ValueError("volto non valido")
    ys = np.linspace(0, image.shape[0] - 1, 64).astype(int)
    xs = np.linspace(0, image.shape[1] - 1, 64).astype(int)
    image = image[np.ix_(ys, xs)]
    image = (image - image.mean()) / max(float(image.std()), 1.0)
    center = image[1:-1, 1:-1]
    neighbors = (image[:-2, :-2], image[:-2, 1:-1], image[:-2, 2:], image[1:-1, 2:],
                 image[2:, 2:], image[2:, 1:-1], image[2:, :-2], image[1:-1, :-2])
    lbp = np.zeros_like(center, dtype=np.uint8)
    for bit, neighbor in enumerate(neighbors):
        lbp |= ((neighbor >= center).astype(np.uint8) << bit)
    features = []
    for rows in np.array_split(lbp, 4, axis=0):
        for block in np.array_split(rows, 4, axis=1):
            hist = np.bincount((block // 16).ravel(), minlength=16).astype(np.float32)
            features.extend(hist / max(float(hist.sum()), 1.0))
    result = np.asarray(features, dtype=np.float32)
    return result / max(float(np.linalg.norm(result)), 1e-8)


def match_face(descriptor, profiles, threshold=.91):
    probe = np.asarray(descriptor, dtype=np.float32)
    best_name, best_score = None, -1.0
    for name, templates in profiles.items():
        for template in templates:
            candidate = np.asarray(template, dtype=np.float32)
            if candidate.shape == probe.shape:
                score = float(np.dot(probe, candidate) / max(np.linalg.norm(probe) * np.linalg.norm(candidate), 1e-8))
                if score > best_score:
                    best_name, best_score = name, score
    matched = best_score >= threshold
    return {"name": best_name if matched else None, "score": max(0.0, best_score), "matched": matched}
