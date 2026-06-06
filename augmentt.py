import albumentations as A
import cv2
import os
import glob

from tqdm import tqdm

# === KONFIGURASI ===
# Layout export dari yolo-annotator: images/<split> + labels/<split> paralel.
# Output ditaruh ke folder train yang SAMA (file diberi prefix unik),
# sehingga file asli tetap ada dan data.yaml tidak perlu diubah.
INPUT_IMAGES  = './export/images/train'
INPUT_LABELS  = './export/labels/train'
OUTPUT_IMAGES = './export/images/train'
OUTPUT_LABELS = './export/labels/train'

AUG_PER_IMAGE = 4          # tiap gambar -> 4 copy augment (train jadi ~5x lipat)
AUG_PREFIX    = 'aug_v'    # penanda file hasil augment (dilewati saat re-run)
MIN_VISIBILITY = 0.3       # box yang tersisa < 30% setelah transform dibuang

os.makedirs(OUTPUT_IMAGES, exist_ok=True)
os.makedirs(OUTPUT_LABELS, exist_ok=True)

# === PIPELINE AUGMENTASI (moderat, aman untuk angka/meter) ===
# Geometri sengaja ringan supaya digit kecil tidak rusak/terpotong berlebihan.
transform = A.Compose([
    A.Affine(scale=(0.9, 1.1), translate_percent=(0.0, 0.06),
            rotate=(-7, 7), shear=(-5, 5), p=0.5),
    A.OneOf([
        A.RandomSunFlare(flare_roi=(0, 0, 1, 0.5), src_radius=200,
                        src_color=(255, 255, 255), p=1.0),
        A.RandomShadow(shadow_dimension=5, shadow_roi=(0, 0, 1, 1), p=1.0),
    ], p=0.7),
    A.OneOf([
        A.ISONoise(color_shift=(0.01, 0.05), intensity=(0.1, 0.5), p=1.0),
        A.CLAHE(clip_limit=4.0, tile_grid_size=(8, 8), p=1.0),
        A.MotionBlur(blur_limit=7, p=1.0),
        A.Downscale(scale_range=(0.5, 0.9), p=1.0),
    ], p=0.6),
    A.CoarseDropout(num_holes_range=(2, 6), hole_height_range=(8, 20),
                    hole_width_range=(8, 20), p=0.3),
    A.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2, hue=0.02, p=0.3),
], bbox_params=A.BboxParams(format='yolo', label_fields=['class_labels'],
                            min_visibility=MIN_VISIBILITY))


# --- Helper ---
def read_yolo_label(label_path):
    bboxes, class_labels = [], []
    if os.path.exists(label_path):
        with open(label_path, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    class_labels.append(int(parts[0]))
                    bboxes.append([float(x) for x in parts[1:5]])
    return bboxes, class_labels


def save_yolo_label(save_path, bboxes, class_labels):
    with open(save_path, 'w') as f:
        for bbox, cls in zip(bboxes, class_labels):
            f.write(f"{cls} {' '.join(map(str, bbox))}\n")


# === EKSEKUSI ===
image_paths = sorted(
    p for p in glob.glob(os.path.join(INPUT_IMAGES, '*.jpg'))
    if not os.path.basename(p).startswith(AUG_PREFIX)   # jangan augment hasil augment
)
total_original = len(image_paths)
generated_count = 0
skipped_no_box = 0
failed = 0
dropped_all_boxes = 0   # augment yang semua box-nya hilang -> tidak disimpan

print("Mulai augmentasi uniform (tiap gambar dibuat sama banyak)...")
print(f"Dataset awal (train): {total_original} gambar, target {AUG_PER_IMAGE}x per gambar")

for img_path in tqdm(image_paths):
    image = cv2.imread(img_path)
    if image is None:
        failed += 1
        continue
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    basename = os.path.basename(img_path)
    stem = os.path.splitext(basename)[0]
    label_path = os.path.join(INPUT_LABELS, stem + '.txt')

    bboxes, class_labels = read_yolo_label(label_path)
    if not bboxes:
        skipped_no_box += 1
        continue

    for i in range(AUG_PER_IMAGE):
        try:
            out = transform(image=image, bboxes=bboxes, class_labels=class_labels)
        except Exception as e:
            failed += 1
            continue

        # Semua box hilang karena ter-crop/transform -> buang, jangan simpan label kosong
        if len(out['bboxes']) == 0:
            dropped_all_boxes += 1
            continue

        new_stem = f"{AUG_PREFIX}{i}_{stem}"
        save_img = os.path.join(OUTPUT_IMAGES, new_stem + '.jpg')
        save_lbl = os.path.join(OUTPUT_LABELS, new_stem + '.txt')

        cv2.imwrite(save_img, cv2.cvtColor(out['image'], cv2.COLOR_RGB2BGR))
        save_yolo_label(save_lbl, out['bboxes'], out['class_labels'])
        generated_count += 1

# === SANITY CHECK & LAPORAN ===
n_img = len(glob.glob(os.path.join(OUTPUT_IMAGES, '*.jpg')))
n_lbl = len(glob.glob(os.path.join(OUTPUT_LABELS, '*.txt')))

print("\n" + "=" * 44)
print("           LAPORAN AUGMENTASI            ")
print("=" * 44)
print(f"Gambar asli (train)      : {total_original}")
print(f"Gambar baru di-generate  : {generated_count}")
print(f"Dilewati (tanpa box)     : {skipped_no_box}")
print(f"Gagal baca/transform     : {failed}")
print(f"Augment dibuang (0 box)  : {dropped_all_boxes}")
print("-" * 44)
print(f"Total file di train       : {n_img} images / {n_lbl} labels")
if n_img != n_lbl:
    print("⚠️   JUMLAH IMAGES != LABELS — cek lagi sebelum training!")
else:
    print("✅ images & labels sinkron.")
print("=" * 44)
print(f"Lokasi output: {OUTPUT_IMAGES}")

