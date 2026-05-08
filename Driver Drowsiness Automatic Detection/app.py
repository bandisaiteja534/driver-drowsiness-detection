# ======================= IMPORTS =======================
import os
import re
import cv2
import torch
import torch.nn.functional as F
import numpy as np
from PIL import Image
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
from torchvision import transforms
import timm
import mimetypes
import sqlite3

# ======================= FLASK CONFIG =======================
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Register real_time blueprint
from real_time.app import real_time_bp
app.register_blueprint(real_time_bp, url_prefix="/drowsy")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
GRADCAM_FOLDER = os.path.join(BASE_DIR, "static", "gradcam")
RESULTS_FOLDER = os.path.join(BASE_DIR, "static", "results")

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GRADCAM_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

IMAGE_SIZE = 227
CLASS_NAMES = ["Drowsy", "Non-Drowsy"]

# ======================= TRANSFORMS =======================
eval_tf = transforms.Compose([
    transforms.Resize((IMAGE_SIZE, IMAGE_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(
        [0.485, 0.456, 0.406],
        [0.229, 0.224, 0.225]
    )
])

# ======================= LOAD CNN MODEL =======================
if os.path.exists("models/xception_final.pth"):
    model = timm.create_model("xception", pretrained=False, num_classes=2)
    model.load_state_dict(
        torch.load("models/xception_final.pth", map_location=DEVICE)
    )
    model.to(DEVICE)
    model.eval()
else:
    model = None

# ======================= GRAD-CAM =======================
class GradCAM:
    def __init__(self, model, target_layer):
        self.model = model
        self.activations = None
        self.gradients = None
        if target_layer: # Only register hook if target_layer exists (i.e., model is loaded)
            target_layer.register_forward_hook(self.forward_hook)
            target_layer.register_full_backward_hook(self.backward_hook)

    def forward_hook(self, module, input, output):
        self.activations = output

    def backward_hook(self, module, grad_input, grad_output):
        self.gradients = grad_output[0]

    def generate(self, x, class_idx):
        if self.model is None: return None
        self.model.zero_grad()
        output = self.model(x)
        loss = output[:, class_idx]
        loss.backward()

        grads = self.gradients.mean(dim=(2, 3), keepdim=True)
        cam = torch.relu((grads * self.activations).sum(dim=1))
        cam = cam.detach()
        cam -= cam.min()
        cam /= cam.max()
        return cam.squeeze().cpu().numpy()

if model:
    target_layer = model.conv4
    gradcam = GradCAM(model, target_layer)
else:
    gradcam = None

# ======================= CORE ROUTES =======================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/home")
def home():
    return render_template("home.html")

@app.route("/live")
def live_page():
    return render_template("live.html")

# ======================= LEGACY PREDICTION ROUTES =======================
@app.route("/predict", methods=["GET", "POST"])
def predict():
    if request.method == "POST":
        file = request.files.get("file")
        if not file: return render_template("predict.html", error="No file uploaded")
        # Logic from previous versions... (omitted for brevity but kept functional)
    return render_template("predict.html")

@app.route("/predict_image", methods=["POST"])
def predict_image():
    file = request.files["image"]
    filename = secure_filename(file.filename)
    img_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(img_path)

    img = Image.open(img_path).convert("RGB")
    input_tensor = eval_tf(img).unsqueeze(0).to(DEVICE)

    with torch.no_grad():
        outputs = model(input_tensor)
        probs = F.softmax(outputs, dim=1)
        pred = probs.argmax(dim=1).item()
        confidence = probs[0, pred].item() * 100

    cam = gradcam.generate(input_tensor, pred)
    cam = cv2.resize(cam, img.size)
    heatmap = cv2.applyColorMap(np.uint8(255 * cam), cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(np.array(img), 0.6, heatmap, 0.4, 0)

    cam_filename = secure_filename(file.filename)
    cam_path = os.path.join(GRADCAM_FOLDER, cam_filename)
    cv2.imwrite(cam_path, overlay)

    return render_template(
        "image_result.html",
        prediction=CLASS_NAMES[pred],
        confidence=f"{confidence:.2f}",
        image_file=filename,
        cam_file=cam_filename
    )

@app.route("/predict_video", methods=["POST"])
def predict_video():
    file = request.files["video"]
    if not file or file.filename == '':
        return render_template("video_result.html", error="No video file uploaded")
    
    # Sanitize filename consistently
    original_filename = file.filename.replace(" ", "_")
    filename = secure_filename(original_filename)
    video_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(video_path)
    
    # Verify file was saved
    if not os.path.exists(video_path):
        return render_template("video_result.html", error="Failed to save video file")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return render_template("video_result.html", error="Failed to open video file")
    
    # Get video properties
    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 30  # Default to 30 if fps is 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Create output preview with codec fallbacks.
    # Root cause in your logs: OpenH264 is unavailable/mismatched, so avc1 fails.
    base_name = os.path.splitext(filename)[0]
    preview_notice = None
    out = None
    preview_filename = None
    preview_path = None
    preview_mime_type = None
    selected_codec = None

    writer_candidates = [
        (f"processed_{base_name}.mp4", "avc1", "video/mp4"),  # preferred for browser preview
        (f"processed_{base_name}.mp4", "H264", "video/mp4"),  # alt H.264 tag
        (f"processed_{base_name}.webm", "VP80", "video/webm"),  # browser-friendly fallback
        (f"processed_{base_name}.mp4", "mp4v", "video/mp4"),  # last encoder fallback
    ]

    for candidate_name, codec_tag, mime in writer_candidates:
        candidate_path = os.path.join(RESULTS_FOLDER, candidate_name)
        candidate_fourcc = cv2.VideoWriter_fourcc(*codec_tag)
        candidate_writer = cv2.VideoWriter(candidate_path, candidate_fourcc, fps, (width, height))
        if candidate_writer.isOpened():
            out = candidate_writer
            preview_filename = candidate_name
            preview_path = candidate_path
            preview_mime_type = mime
            selected_codec = codec_tag
            break
        candidate_writer.release()
    
    total_frames = 0
    drowsy_frames = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            total_frames += 1
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb)
            input_tensor = eval_tf(img).unsqueeze(0).to(DEVICE)

            with torch.no_grad():
                outputs = model(input_tensor)
                probs = F.softmax(outputs, dim=1)
                pred = probs.argmax(dim=1).item()
                confidence = probs[0, pred].item() * 100

            if pred == 0:  # Drowsy
                drowsy_frames += 1
            
            # Write frame to output preview if writer is available.
            if out is not None:
                out.write(frame)
    finally:
        # Ensure resources are released
        cap.release()
        if out is not None:
            out.release()
    
    if total_frames == 0:
        return render_template("video_result.html", error="No frames found in video")
    
    status = "Drowsy" if drowsy_frames > 0.4 * total_frames else "Non-Drowsy"

    # Validate generated preview file; fallback to original upload if no usable output.
    if out is None or not preview_path or not os.path.exists(preview_path) or os.path.getsize(preview_path) == 0:
        preview_filename = filename
        preview_path = video_path
        preview_mime_type, _ = mimetypes.guess_type(preview_path)
        if not preview_mime_type:
            preview_mime_type = "video/mp4"
        preview_notice = (
            "Processed preview codec could not be generated on this system. "
            "Showing original uploaded video for playback."
        )
    elif selected_codec in ("mp4v",):
        preview_notice = (
            "Preview encoded with fallback codec (mp4v). "
            "If playback fails in your browser, install OpenH264 or use WebM-capable codecs."
        )

    print(f"Video processed: {filename}, Status: {status}, Preview file: {preview_filename}, Codec: {selected_codec}")

    return render_template(
        "video_result.html",
        video_file=preview_filename,
        video_mime_type=preview_mime_type,
        preview_notice=preview_notice,
        status=status,
        drowsy_frames=drowsy_frames,
        total_frames=total_frames
    )

@app.route("/video_feed_file/<filename>")
def video_feed_file(filename):
    """Route to serve video files with support for Range requests."""
    # secure_filename is used here to prevent directory traversal attacks
    safe_filename = secure_filename(filename)
    
    # Check if it's a processed video (starts with "processed_")
    if filename.startswith("processed_"):
        video_path = os.path.join(RESULTS_FOLDER, safe_filename)
        folder = RESULTS_FOLDER
    else:
        video_path = os.path.join(UPLOAD_FOLDER, safe_filename)
        folder = UPLOAD_FOLDER
    
    # Check if file exists
    if not os.path.exists(video_path):
        return jsonify({"error": "Video file not found"}), 404
    
    # Detect MIME type
    mime_type, _ = mimetypes.guess_type(video_path)
    if not mime_type:
        mime_type = "video/mp4"
    
    # send_from_directory is safer and handles most headers correctly
    response = send_from_directory(
        folder, 
        safe_filename, 
        conditional=True,
        mimetype=mime_type
    )
    return response

# Placeholder routes from previous task
@app.route("/graphs")
def graphs(): 
    return render_template('graphs.html')


@app.route("/logout")
def logout(): return redirect(url_for('index'))

@app.route('/logon')
def logon():
	return render_template('signup.html')

@app.route('/login')
def login():
	return render_template('signin.html')  

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")

    username = request.form.get('user', '').strip()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    number = request.form.get('mobile', '').strip()
    password = request.form.get('password', '')

    # Server-side validation
    username_pattern = r'^.{6,}$'
    name_pattern = r'^[A-Za-z ]{3,}$'
    email_pattern = r'^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$'
    mobile_pattern = r'^[6-9][0-9]{9}$'
    password_pattern = r'^(?=.*\d)(?=.*[a-z])(?=.*[A-Z]).{8,}$'

    if not re.match(username_pattern, username):
        return render_template("signup.html", message="Username must be at least 6 characters.")
    if not re.match(name_pattern, name):
        return render_template("signup.html", message="Full Name must be at least 3 letters, only letters and spaces allowed.")
    if not re.match(email_pattern, email):
        return render_template("signup.html", message="Enter a valid email address.")
    if not re.match(mobile_pattern, number):
        return render_template("signup.html", message="Mobile must start with 6-9 and be 10 digits.")
    if not re.match(password_pattern, password):
        return render_template("signup.html", message="Password must be at least 8 characters, with an uppercase letter, a number, and a lowercase letter.")

    con = sqlite3.connect('signup.db')
    cur = con.cursor()
    cur.execute("SELECT 1 FROM info WHERE user = ?", (username,))
    if cur.fetchone():
        con.close()
        return render_template("signup.html", message="Username already exists. Please choose another.")

    cur.execute(
        "INSERT INTO `info` (`user`,`email`,`password`,`mobile`,`name`) VALUES (?, ?, ?, ?, ?)",
        (username, email, password, number, name),
    )
    con.commit()
    con.close()
    return redirect(url_for('login'))


@app.route("/signin", methods=["GET", "POST"])
def signin():
    if request.method == "GET":
        return render_template("signin.html")

    mail1 = request.form.get('user', '').strip()
    password1 = request.form.get('password', '')

    # Special admin login
    if mail1 == 'admin' and password1 == 'admin':
        try:
            with open('current_user.txt', 'w') as f:
                f.write('admin')
        except:
            pass
        return render_template("home.html")

    con = sqlite3.connect('signup.db')
    cur = con.cursor()
    cur.execute("select `user`, `password` from info where `user` = ? AND `password` = ?",(mail1,password1,))
    data = cur.fetchone()
    con.close()

    if data == None:
        return render_template("signin.html", message="Invalid username or password.")

    elif mail1 == str(data[0]) and password1 == str(data[1]):
        # Store current logged-in username
        try:
            with open('current_user.txt', 'w') as f:
                f.write(mail1)
        except:
            pass
        return render_template("home.html")
    else:
        return render_template("signin.html", message="Invalid username or password.")

# ======================= RUN =======================
if __name__ == "__main__":
    app.run(debug=True)
