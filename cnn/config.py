"""Shared config for the meter-digit CNN."""

# Generous digit-band crop (fractions of the rotated-upright frame), wide enough
# to contain all 9 digits across the camera DRIFT in the dataset. The CNN +
# random shift/scale augmentation absorb the residual movement.
CROP = (0.02, 0.02, 0.92, 0.46)

# Frames are stored upside-down (camera mount).
ROTATE_180 = True

# CNN input (grayscale). Digits are a wide row -> wide aspect.
IN_H = 64
IN_W = 256

N_DIGITS = 9
N_CLASSES = 10            # 0-9. "unreadable" is handled by LOW CONFIDENCE, not a class.

# Route a read to the oracle when ANY digit's softmax confidence is below this.
# Start conservative (lots go to oracle); raise as the CNN proves out.
CONF_THRESHOLD = 0.90
