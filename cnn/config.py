"""Shared config for the meter-digit CNN."""

# Location-2 fixed-camera digit-band crop. Keep this aligned with retrain.py
# and cnn_service.py so local tools evaluate the same image geometry as live.
CROP = (0.10, 0.45, 0.84, 0.73)

# Frames are stored upside-down (camera mount).
ROTATE_180 = True

# CNN input (grayscale). Digits are a wide row -> wide aspect.
IN_H = 64
IN_W = 256

N_DIGITS = 9
N_CLASSES = 10            # 0-9. "unreadable" is handled by LOW CONFIDENCE, not a class.

# Route a read to the oracle when ANY digit's softmax confidence is below this.
# Start conservative (lots go to oracle); raise as the CNN proves out.
CONF_THRESHOLD = 0.95
