"""Trains the fence detector (YOLO11n) on the auto-labelled Gazebo dataset and exports ONNX for the Jetson.

    python tools/train_yolo.py [--epochs 25] [--device cpu|mps] [--data ~/querra-data/fence_yolo/data.yaml]
    python tools/train_yolo.py --resume ~/querra-data/train/<name>/weights/last.pt   (after Ctrl+C / a pause)
    (needs: pip install ultralytics onnx onnxslim)

On the 8 GB M2 Mac: --device mps --batch 8 --workers 0 trains 4x faster than the CPU with the same scores (ground-v0.2's
first epoch: 4.9 min, mAP50 0.923, against 19.8 min and 0.923). --batch 16 on mps does not fit: memory and swap fill
up and it runs slower than the CPU.

Output: ~/querra-data/train/<name>/weights/best.pt and best.onnx (input 1x3x416x640, for 640x400 frames).
"""
import argparse
import os

from ultralytics import YOLO

ap = argparse.ArgumentParser()
ap.add_argument("--data", default=os.path.expanduser("~/querra-data/fence_yolo/data.yaml"))
ap.add_argument("--model", default="yolo11n.pt")
ap.add_argument("--epochs", type=int, default=25)
ap.add_argument("--batch", type=int, default=16)
ap.add_argument("--imgsz", type=int, default=640)
ap.add_argument("--device", default="mps", help="mps on Apple Silicon, cpu, or a CUDA index (v0.2 was trained with cpu)")
ap.add_argument("--workers", type=int, default=2)
ap.add_argument("--cache", default=False, help="ram to cache images (needs ~4 GB free)")
ap.add_argument("--project", default=os.path.expanduser("~/querra-data/train"))
ap.add_argument("--name", default="fence-yolo11n")
ap.add_argument("--export-only", help="path to best.pt: skip training, only validate + export")
ap.add_argument("--resume", help="path to an interrupted run's weights/last.pt: continue it with its own settings")
args = ap.parse_args()

project = args.project
if args.export_only:
    best = args.export_only
elif args.resume:  # same data, epochs and optimizer state as the interrupted run
    YOLO(args.resume).train(resume=True)
    best = os.path.join(os.path.dirname(args.resume), "best.pt")
else:
    model = YOLO(args.model)
    model.train(data=args.data, epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, device=args.device,
                workers=args.workers, project=project, name=args.name, exist_ok=True, cache=args.cache, patience=10,
                fliplr=0.5, flipud=0.0, degrees=5, mosaic=1.0, close_mosaic=3, hsv_v=0.5, plots=True)
    best = os.path.join(project, args.name, "weights", "best.pt")
model = YOLO(best)
metrics = model.val(data=args.data, imgsz=args.imgsz, batch=args.batch, device=args.device, plots=False)
for i, name in model.names.items():
    print("val %-12s mAP50 %.3f  mAP50-95 %.3f" % (name, metrics.box.ap50[i] if i < len(metrics.box.ap50) else float("nan"),
                                                    metrics.box.maps[i]))
print("val all          mAP50 %.3f  mAP50-95 %.3f" % (metrics.box.map50, metrics.box.map))
print("onnx:", model.export(format="onnx", imgsz=(416, 640), opset=17, simplify=True, dynamic=False))
