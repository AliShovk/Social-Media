import argparse
import hashlib
import json
import os
import random
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import cv2
import requests
import vk_api
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from vk_api.exceptions import ApiError


load_dotenv()


def env_value(name, default=None):
    return os.getenv(name) or default


VK_USER_TOKEN = os.getenv("VK_USER_TOKEN")
VK_GROUP_ID = os.getenv("VK_GROUP_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OK_ACCESS_TOKEN = os.getenv("OK_ACCESS_TOKEN")
OK_APPLICATION_KEY = os.getenv("OK_APPLICATION_KEY")
OK_APPLICATION_SECRET_KEY = os.getenv("OK_APPLICATION_SECRET_KEY")
OK_GROUP_ID = os.getenv("OK_GROUP_ID")
YOUTUBE_CLIENT_SECRETS_FILE = env_value("YOUTUBE_CLIENT_SECRETS_FILE", "client_secret.json")
YOUTUBE_TOKEN_FILE = env_value("YOUTUBE_TOKEN_FILE", "youtube_token.json")
YOUTUBE_PRIVACY_STATUS = env_value("YOUTUBE_PRIVACY_STATUS", "public")
SOURCE_VIDEO_URL = env_value("SOURCE_VIDEO_URL")
SOURCE_MEDIA_BASE_URL = env_value("SOURCE_MEDIA_BASE_URL")
DOWNLOAD_HISTORY_FILE = Path(env_value("DOWNLOAD_HISTORY_FILE", "downloaded_videos.json"))
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
SITE_URL = "https://masterhacks.ru/"
SITE_CTA = "👇 Переходите на сайт 👇"
HASHTAGS_FILE = Path("hashtags.txt")
HASHTAGS_PER_POST = 5
VIDEO_TITLE_MAX_LENGTH = 7
PROCESSED_FOLDER = Path("videos/processed")
CARTOON_MAX_HEIGHT = 720
CARTOON_FPS = 24
UNIQUE_MAX_HEIGHT = 720
UNIQUE_FPS = 30
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class VkAutoposterError(Exception):
    pass


class TelegramAutoposterError(Exception):
    pass


class OkAutoposterError(Exception):
    pass


class YoutubeAutoposterError(Exception):
    pass


class VideoLinkParser(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name in ("href", "src"):
            value = attrs.get(name)
            if value:
                url = urljoin(self.base_url, value)
                if Path(urlparse(url).path).suffix.lower() in VIDEO_EXTENSIONS:
                    self.links.append(url)


def load_download_history():
    if not DOWNLOAD_HISTORY_FILE.is_file():
        return set()

    try:
        return set(json.loads(DOWNLOAD_HISTORY_FILE.read_text(encoding="utf-8")))
    except json.JSONDecodeError:
        return set()


def save_download_history(history):
    DOWNLOAD_HISTORY_FILE.write_text(
        json.dumps(sorted(history), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def video_filename_from_url(url):
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    if name:
        return name

    digest = hashlib.md5(url.encode("utf-8")).hexdigest()
    return f"{digest}.mp4"


def find_source_video_urls(source_url):
    response = requests.get(source_url, timeout=30)
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()
    if Path(urlparse(source_url).path).suffix.lower() in VIDEO_EXTENSIONS:
        return [source_url]

    if "json" in content_type:
        data = response.json()
        if isinstance(data, list):
            urls = []
            for item in data:
                if isinstance(item, str) and Path(urlparse(item).path).suffix.lower() in VIDEO_EXTENSIONS:
                    urls.append(item)
                elif isinstance(item, dict):
                    filename = item.get("filename") or item.get("file") or item.get("url")
                    file_type = item.get("type") or item.get("file_type")
                    if not filename:
                        continue

                    if file_type and file_type != "video":
                        continue

                    if filename.startswith(("http://", "https://")):
                        url = filename
                    else:
                        base_url = SOURCE_MEDIA_BASE_URL or urljoin(source_url, "media/")
                        url = urljoin(base_url, filename)

                    if Path(urlparse(url).path).suffix.lower() in VIDEO_EXTENSIONS:
                        urls.append(url)

            return list(dict.fromkeys(urls))

    parser = VideoLinkParser(source_url)
    parser.feed(response.text)
    return list(dict.fromkeys(parser.links))


def download_new_videos(source_url, target_folder):
    if not source_url:
        print("SOURCE_VIDEO_URL is not configured. Skipping video download.")
        return []

    target = Path(target_folder)
    target.mkdir(parents=True, exist_ok=True)
    history = load_download_history()
    downloaded = []
    video_urls = find_source_video_urls(source_url)

    if not video_urls:
        print(f"No source videos found: {source_url}")
        return []

    for video_url in video_urls:
        if video_url in history:
            continue

        filename = video_filename_from_url(video_url)
        destination = target / filename
        if destination.exists():
            history.add(video_url)
            continue

        print(f"Downloading video: {video_url}")
        with requests.get(video_url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with destination.open("wb") as file:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file.write(chunk)

        history.add(video_url)
        downloaded.append(destination)
        print(f"Downloaded video: {destination}")

    save_download_history(history)

    if not downloaded:
        print("No new videos to download.")

    return downloaded


def load_hashtags():
    if not HASHTAGS_FILE.is_file():
        return []

    hashtags = []
    for line in HASHTAGS_FILE.read_text(encoding="utf-8").splitlines():
        hashtag = line.strip()
        if hashtag:
            hashtags.append(hashtag)

    return hashtags


def build_post_message(message):
    parts = [message.strip() if message else ""]
    parts.append(SITE_CTA)
    parts.append(SITE_URL)

    hashtags = load_hashtags()
    if hashtags:
        selected_hashtags = random.sample(hashtags, min(HASHTAGS_PER_POST, len(hashtags)))
        parts.append(" ".join(selected_hashtags))

    return "\n\n".join(part for part in parts if part)


def shorten_video_title(title):
    return title[:VIDEO_TITLE_MAX_LENGTH]


def apply_cartoon_effect_to_frame(frame):
    color = cv2.bilateralFilter(frame, d=3, sigmaColor=25, sigmaSpace=25)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 3)
    edges = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_MEAN_C,
        cv2.THRESH_BINARY,
        7,
        2,
    )
    edges = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    cartoon = cv2.bitwise_and(color, edges)
    sharpened = cv2.addWeighted(cartoon, 1.7, cv2.GaussianBlur(cartoon, (0, 0), 0.8), -0.7, 0)
    return cv2.convertScaleAbs(sharpened, alpha=1.08, beta=4)


def apply_stylization_effect_to_frame(frame):
    stylized = cv2.stylization(frame, sigma_s=60, sigma_r=0.45)
    return cv2.addWeighted(stylized, 0.68, frame, 0.32, 0)


def process_video_cartoon(video_path):
    source = Path(video_path)
    if not source.is_file():
        raise VkAutoposterError(f"Video file not found: {source}")

    PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    destination = PROCESSED_FOLDER / f"{source.stem}_cartoon.mp4"

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise VkAutoposterError(f"Cannot open video for processing: {source}")

    source_fps = capture.get(cv2.CAP_PROP_FPS) or 25
    fps = min(source_fps, CARTOON_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    output_width = width
    output_height = height

    if height > CARTOON_MAX_HEIGHT:
        scale = CARTOON_MAX_HEIGHT / height
        output_width = int(width * scale)
        output_height = CARTOON_MAX_HEIGHT

    if output_width % 2:
        output_width -= 1

    if output_height % 2:
        output_height -= 1

    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(destination), fourcc, fps, (output_width, output_height))

    if not writer.isOpened():
        capture.release()
        raise VkAutoposterError(f"Cannot create processed video: {destination}")

    processed_frames = 0
    print(f"Applying cartoon effect: {source}")

    while True:
        success, frame = capture.read()
        if not success:
            break

        if (output_width, output_height) != (width, height):
            frame = cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_AREA)

        writer.write(apply_cartoon_effect_to_frame(frame))
        processed_frames += 1

        if frame_count and processed_frames % max(1, frame_count // 10) == 0:
            percent = int(processed_frames * 100 / frame_count)
            print(f"Processing progress: {min(percent, 100)}%")

    capture.release()
    writer.release()

    print(f"Processed video saved: {destination}")
    return destination


def process_video_stylization(video_path):
    source = Path(video_path)
    if not source.is_file():
        raise VkAutoposterError(f"Video file not found: {source}")

    PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    destination = PROCESSED_FOLDER / f"{source.stem}_stylization.mp4"

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise VkAutoposterError(f"Cannot open video for processing: {source}")

    source_fps = capture.get(cv2.CAP_PROP_FPS) or 25
    fps = min(source_fps, CARTOON_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    output_width = width
    output_height = height

    if height > CARTOON_MAX_HEIGHT:
        scale = CARTOON_MAX_HEIGHT / height
        output_width = int(width * scale)
        output_height = CARTOON_MAX_HEIGHT

    if output_width % 2:
        output_width -= 1

    if output_height % 2:
        output_height -= 1

    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(destination), fourcc, fps, (output_width, output_height))

    if not writer.isOpened():
        capture.release()
        raise VkAutoposterError(f"Cannot create processed video: {destination}")

    processed_frames = 0
    print(f"Applying stylization effect: {source}")

    while True:
        success, frame = capture.read()
        if not success:
            break

        if (output_width, output_height) != (width, height):
            frame = cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_AREA)

        writer.write(apply_stylization_effect_to_frame(frame))
        processed_frames += 1

        if frame_count and processed_frames % max(1, frame_count // 10) == 0:
            percent = int(processed_frames * 100 / frame_count)
            print(f"Processing progress: {min(percent, 100)}%")

    capture.release()
    writer.release()

    print(f"Processed video saved: {destination}")
    return destination


def apply_unique_effect_to_frame(frame):
    height, width = frame.shape[:2]
    crop_x = max(2, int(width * 0.025))
    crop_y = max(2, int(height * 0.025))
    cropped = frame[crop_y:height - crop_y, crop_x:width - crop_x]
    resized = cv2.resize(cropped, (width, height), interpolation=cv2.INTER_LINEAR)
    adjusted = cv2.convertScaleAbs(resized, alpha=1.06, beta=3)
    hsv = cv2.cvtColor(adjusted, cv2.COLOR_BGR2HSV)
    hsv[:, :, 1] = cv2.convertScaleAbs(hsv[:, :, 1], alpha=1.08, beta=0)
    adjusted = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    blurred = cv2.GaussianBlur(adjusted, (0, 0), 0.8)
    return cv2.addWeighted(adjusted, 1.25, blurred, -0.25, 0)


def process_video_unique(video_path):
    source = Path(video_path)
    if not source.is_file():
        raise VkAutoposterError(f"Video file not found: {source}")

    PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    destination = PROCESSED_FOLDER / f"{source.stem}_unique.mp4"

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise VkAutoposterError(f"Cannot open video for processing: {source}")

    source_fps = capture.get(cv2.CAP_PROP_FPS) or 25
    fps = min(max(source_fps, 24), UNIQUE_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    output_width = width
    output_height = height

    if height > UNIQUE_MAX_HEIGHT:
        scale = UNIQUE_MAX_HEIGHT / height
        output_width = int(width * scale)
        output_height = UNIQUE_MAX_HEIGHT

    if output_width % 2:
        output_width -= 1

    if output_height % 2:
        output_height -= 1

    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(destination), fourcc, fps, (output_width, output_height))

    if not writer.isOpened():
        capture.release()
        raise VkAutoposterError(f"Cannot create processed video: {destination}")

    processed_frames = 0
    print(f"Applying unique effect: {source}")

    while True:
        success, frame = capture.read()
        if not success:
            break

        if (output_width, output_height) != (width, height):
            frame = cv2.resize(frame, (output_width, output_height), interpolation=cv2.INTER_AREA)

        writer.write(apply_unique_effect_to_frame(frame))
        processed_frames += 1

        if frame_count and processed_frames % max(1, frame_count // 10) == 0:
            percent = int(processed_frames * 100 / frame_count)
            print(f"Processing progress: {min(percent, 100)}%")

    capture.release()
    writer.release()

    print(f"Processed video saved: {destination}")
    return destination


def get_vk_api():
    if not VK_USER_TOKEN:
        raise VkAutoposterError("VK_USER_TOKEN is missing. Add it to your .env file.")

    token = VK_USER_TOKEN.strip().split("&", 1)[0]
    session = vk_api.VkApi(token=token)
    return session.get_api()


def get_group_id():
    if not VK_GROUP_ID:
        raise VkAutoposterError("VK_GROUP_ID is missing. Add it to your .env file.")

    try:
        group_id = int(VK_GROUP_ID)
    except ValueError as exc:
        raise VkAutoposterError("VK_GROUP_ID must be a number, for example -123456789.") from exc

    if group_id > 0:
        group_id = -group_id

    return group_id


def upload_wall_photo(vk, group_id, image_path):
    path = Path(image_path)
    if not path.is_file():
        raise VkAutoposterError(f"Image file not found: {path}")

    upload_server = vk.photos.getWallUploadServer(group_id=abs(group_id))

    with path.open("rb") as image_file:
        response = requests.post(
            upload_server["upload_url"],
            files={"photo": image_file},
            timeout=60,
        )

    response.raise_for_status()
    upload_data = response.json()

    if "error" in upload_data:
        raise VkAutoposterError(f"VK upload error: {upload_data['error']}")

    saved_photos = vk.photos.saveWallPhoto(
        group_id=abs(group_id),
        photo=upload_data["photo"],
        server=upload_data["server"],
        hash=upload_data["hash"],
    )

    if not saved_photos:
        raise VkAutoposterError("VK did not return saved photo data.")

    photo = saved_photos[0]
    return f"photo{photo['owner_id']}_{photo['id']}"


def upload_video(vk, group_id, video_path, title, description):
    path = Path(video_path)
    if not path.is_file():
        raise VkAutoposterError(f"Video file not found: {path}")

    upload_info = vk.video.save(
        group_id=abs(group_id),
        name=title,
        description=description,
        wallpost=0,
    )

    with path.open("rb") as video_file:
        response = requests.post(
            upload_info["upload_url"],
            files={"video_file": video_file},
            timeout=600,
        )

    response.raise_for_status()
    upload_data = response.json()

    if "error" in upload_data:
        raise VkAutoposterError(f"VK video upload error: {upload_data['error']}")

    owner_id = upload_info.get("owner_id") or upload_data.get("owner_id")
    video_id = upload_info.get("video_id") or upload_data.get("video_id")

    if not owner_id or not video_id:
        raise VkAutoposterError(f"VK did not return video attachment data: {upload_data}")

    return f"video{owner_id}_{video_id}"


def publish_post(message, image_paths=None, video_paths=None, video_title=None):
    vk = get_vk_api()
    group_id = get_group_id()
    attachments = []
    post_message = build_post_message(message)

    for image_path in image_paths or []:
        attachments.append(upload_wall_photo(vk, group_id, image_path))

    for video_path in video_paths or []:
        title = shorten_video_title(video_title or Path(video_path).stem)
        attachments.append(upload_video(vk, group_id, video_path, title, post_message))

    return vk.wall.post(
        owner_id=group_id,
        from_group=1,
        message=post_message,
        attachments=",".join(attachments),
    )


def send_video_to_telegram(video_path, caption):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram is not configured. Skipping Telegram publish.")
        return None

    path = Path(video_path)
    if not path.is_file():
        raise TelegramAutoposterError(f"Telegram video file not found: {path}")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVideo"
    telegram_caption = caption[:1024]

    with path.open("rb") as video_file:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": telegram_caption,
                "supports_streaming": "true",
            },
            files={"video": video_file},
            timeout=600,
        )

    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise TelegramAutoposterError(f"Telegram API error: {result}")

    return result["result"]


def is_ok_configured():
    return all([OK_ACCESS_TOKEN, OK_APPLICATION_KEY, OK_APPLICATION_SECRET_KEY, OK_GROUP_ID])


def build_ok_sig(params):
    session_secret_key = hashlib.md5(
        f"{OK_ACCESS_TOKEN}{OK_APPLICATION_SECRET_KEY}".encode("utf-8")
    ).hexdigest().lower()
    params_for_sig = {
        key: value
        for key, value in params.items()
        if key not in {"access_token", "session_key"} and value is not None
    }
    signature_base = "".join(
        f"{key}={params_for_sig[key]}"
        for key in sorted(params_for_sig)
    )
    return hashlib.md5(f"{signature_base}{session_secret_key}".encode("utf-8")).hexdigest().lower()


def ok_api_call(method, params):
    if not is_ok_configured():
        print("Odnoklassniki is not configured. Skipping OK publish.")
        return None

    request_params = {
        **params,
        "application_key": OK_APPLICATION_KEY,
        "format": "json",
        "method": method,
        "access_token": OK_ACCESS_TOKEN,
    }
    request_params["sig"] = build_ok_sig(request_params)

    response = requests.post("https://api.ok.ru/fb.do", data=request_params, timeout=120)
    response.raise_for_status()
    result = response.json()

    if isinstance(result, dict) and "error_code" in result:
        raise OkAutoposterError(f"OK API error: {result}")

    return result


def upload_video_to_ok(video_path, title):
    path = Path(video_path)
    if not path.is_file():
        raise OkAutoposterError(f"OK video file not found: {path}")

    upload_info = ok_api_call(
        "video.getUploadUrl",
        {
            "gid": OK_GROUP_ID,
            "file_name": path.name,
            "file_size": path.stat().st_size,
            "attachment_type": "MOVIE",
            "post_form": "true",
        },
    )

    if not upload_info:
        return None

    upload_url = upload_info.get("upload_url") or upload_info.get("uploadUrl")
    video_id = upload_info.get("video_id") or upload_info.get("videoId")

    if not upload_url or not video_id:
        raise OkAutoposterError(f"OK did not return upload URL or video ID: {upload_info}")

    with path.open("rb") as video_file:
        upload_response = requests.post(
            upload_url,
            files={"data": video_file},
            timeout=900,
        )

    upload_response.raise_for_status()

    ok_api_call(
        "video.update",
        {
            "vid": video_id,
            "title": title,
            "privacy": "PUBLIC",
        },
    )

    return video_id


def publish_video_to_ok(video_path, message, title):
    if not is_ok_configured():
        print("Odnoklassniki is not configured. Skipping OK publish.")
        return None

    video_id = upload_video_to_ok(video_path, title)
    if not video_id:
        return None

    attachment = {
        "media": [
            {
                "type": "text",
                "text": message,
            },
            {
                "type": "movie",
                "list": [
                    {
                        "id": video_id,
                    }
                ],
            },
        ]
    }

    return ok_api_call(
        "mediatopic.post",
        {
            "gid": OK_GROUP_ID,
            "type": "GROUP_THEME",
            "attachment": json.dumps(attachment, ensure_ascii=False),
        },
    )


def get_youtube_service():
    client_secrets_path = Path(YOUTUBE_CLIENT_SECRETS_FILE)
    token_path = Path(YOUTUBE_TOKEN_FILE)

    if not client_secrets_path.is_file():
        print("YouTube is not configured. Skipping YouTube publish.")
        return None

    credentials = None
    if token_path.is_file():
        credentials = Credentials.from_authorized_user_file(str(token_path), YOUTUBE_SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), YOUTUBE_SCOPES)
            credentials = flow.run_local_server(port=0)

        token_path.write_text(credentials.to_json(), encoding="utf-8")

    return build("youtube", "v3", credentials=credentials)


def publish_video_to_youtube(video_path, message, title):
    youtube = get_youtube_service()
    if not youtube:
        return None

    path = Path(video_path)
    if not path.is_file():
        raise YoutubeAutoposterError(f"YouTube video file not found: {path}")

    youtube_title = shorten_video_title(title)
    description = message
    if "#shorts" not in description.lower():
        description = f"{description}\n\n#shorts"

    media = MediaFileUpload(str(path), chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": youtube_title,
                "description": description,
                "tags": ["shorts", "masterhacks", "лайфхаки"],
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": YOUTUBE_PRIVACY_STATUS,
                "selfDeclaredMadeForKids": False,
            },
        },
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"YouTube upload progress: {int(status.progress() * 100)}%")

    return response


def publish_videos_from_folder(folder_path, posted_folder_path, message, effect):
    folder = Path(folder_path)
    posted_folder = Path(posted_folder_path)

    if not folder.exists():
        folder.mkdir(parents=True)

    posted_folder.mkdir(parents=True, exist_ok=True)

    video_files = sorted(
        path for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    )

    if not video_files:
        print(f"No videos found in folder: {folder}")
        return

    for video_file in video_files:
        post_message = message or shorten_video_title(video_file.stem)
        final_message = build_post_message(post_message)
        publish_video_file = video_file

        if effect == "cartoon":
            publish_video_file = process_video_cartoon(video_file)
        elif effect == "stylization":
            publish_video_file = process_video_stylization(video_file)
        elif effect == "unique":
            publish_video_file = process_video_unique(video_file)

        print(f"Publishing video: {publish_video_file}")
        result = None
        telegram_result = None
        ok_result = None
        youtube_result = None

        try:
            result = publish_post(
                message=post_message,
                video_paths=[str(publish_video_file)],
                video_title=shorten_video_title(video_file.stem),
            )
        except (ApiError, VkAutoposterError, requests.RequestException) as exc:
            print(f"VK publish failed: {exc}")

        try:
            telegram_result = send_video_to_telegram(publish_video_file, final_message)
        except (TelegramAutoposterError, requests.RequestException) as exc:
            print(f"Telegram publish failed: {exc}")

        try:
            ok_result = publish_video_to_ok(
                publish_video_file,
                final_message,
                shorten_video_title(video_file.stem),
            )
        except (OkAutoposterError, requests.RequestException) as exc:
            print(f"Odnoklassniki publish failed: {exc}")

        try:
            youtube_result = publish_video_to_youtube(
                publish_video_file,
                final_message,
                shorten_video_title(video_file.stem),
            )
        except (YoutubeAutoposterError, HttpError, OSError) as exc:
            print(f"YouTube publish failed: {exc}")

        if not any([result, telegram_result, ok_result, youtube_result]):
            print("Video was not published to any platform. Source file was not moved.")
            continue

        destination = posted_folder / video_file.name

        if destination.exists():
            suffix = result["post_id"] if result else "published"
            destination = posted_folder / f"{video_file.stem}_{suffix}{video_file.suffix}"

        shutil.move(str(video_file), str(destination))
        if result:
            print(f"Post published successfully. VK post_id: {result['post_id']}")
        if telegram_result:
            print(f"Telegram video published successfully. message_id: {telegram_result['message_id']}")
        if ok_result:
            print(f"Odnoklassniki video published successfully: {ok_result}")
        if youtube_result:
            print(f"YouTube video published successfully. video_id: {youtube_result['id']}")
        print(f"Moved to: {destination}")


def main():
    parser = argparse.ArgumentParser(description="Post text, photos, and videos to a VK community wall.")
    parser.add_argument("--message", "-m", default=None, help="Post text")
    parser.add_argument("--image", "-i", action="append", default=[], help="Image path. Can be used multiple times.")
    parser.add_argument("--video", "-v", action="append", default=[], help="Video path. Can be used multiple times.")
    parser.add_argument("--video-title", default=None, help="Video title. Defaults to the video file name.")
    parser.add_argument("--video-folder", default=None, help="Folder with new videos to publish.")
    parser.add_argument("--posted-folder", default="videos/posted", help="Folder where published videos will be moved.")
    parser.add_argument("--effect", choices=["none", "cartoon", "stylization", "unique"], default="none", help="Video effect before publishing.")
    parser.add_argument("--download-first", action="store_true", help="Download new videos from SOURCE_VIDEO_URL before publishing.")
    parser.add_argument("--source-url", default=SOURCE_VIDEO_URL, help="URL with source videos. Can be a video file, JSON list, or HTML directory page.")
    args = parser.parse_args()

    try:
        if args.video_folder:
            if args.download_first:
                download_new_videos(args.source_url, args.video_folder)
            publish_videos_from_folder(args.video_folder, args.posted_folder, args.message, args.effect)
            return

        if not args.message:
            raise VkAutoposterError("--message is required when --video-folder is not used.")

        result = publish_post(args.message, args.image, args.video, args.video_title)
    except ApiError as exc:
        raise SystemExit(f"VK API error: {exc}") from exc
    except requests.RequestException as exc:
        raise SystemExit(f"Network error: {exc}") from exc
    except TelegramAutoposterError as exc:
        raise SystemExit(str(exc)) from exc
    except OkAutoposterError as exc:
        raise SystemExit(str(exc)) from exc
    except YoutubeAutoposterError as exc:
        raise SystemExit(str(exc)) from exc
    except VkAutoposterError as exc:
        raise SystemExit(str(exc)) from exc

    print(f"Post published successfully. VK post_id: {result['post_id']}")


if __name__ == "__main__":
    main()
