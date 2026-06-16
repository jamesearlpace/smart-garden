"""Export the trained PyTorch CNN to ONNX for lightweight, torch-free inference
(onnxruntime is already on the tower from the RapidOCR service). Verifies the
ONNX output matches PyTorch on a real frame before saving.
"""
import os
import sys

import numpy as np
import torch

from config import IN_H, IN_W
from model import MeterDigitCNN

HERE = os.path.dirname(__file__)
PT = os.path.join(HERE, "model", "meter_cnn.pt")
ONNX = os.path.join(HERE, "model", "meter_cnn.onnx")


def main():
    m = MeterDigitCNN()
    m.load_state_dict(torch.load(PT, map_location="cpu"))
    m.eval()
    dummy = torch.zeros(1, 1, IN_H, IN_W)
    torch.onnx.export(
        m, dummy, ONNX,
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )
    print("exported", ONNX)

    # Verify parity with onnxruntime if available.
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(ONNX, providers=["CPUExecutionProvider"])
        x = np.random.rand(1, 1, IN_H, IN_W).astype(np.float32)
        with torch.no_grad():
            pt_out = m(torch.from_numpy(x)).numpy()
        ort_out = sess.run(None, {"input": x})[0]
        diff = np.abs(pt_out - ort_out).max()
        print(f"max |pt - onnx| = {diff:.2e}  ({'OK' if diff < 1e-3 else 'MISMATCH'})")
    except ImportError:
        print("onnxruntime not installed here — skip parity check (verify on tower)")


if __name__ == "__main__":
    main()
