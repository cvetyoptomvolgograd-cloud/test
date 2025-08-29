# storage.py
import os
import io
import uuid
import asyncio
import logging
from typing import Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from aiogram import Bot
from utils import convert_heic_to_jpeg


class YandexObjectStorage:
    """Thin async wrapper around boto3 S3 client for Yandex Object Storage."""
    def __init__(self) -> None:
        # ENV variable names follow your .env (YC_*)
        self.access_key_id = os.getenv("YC_ACCESS_KEY_ID")
        self.secret_access_key = os.getenv("YC_SECRET_ACCESS_KEY")
        self.bucket_name = os.getenv("YC_BUCKET_NAME")
        self.endpoint_url = os.getenv("YC_ENDPOINT_URL")
        self.s3_client = None
        self.initialized = False

    def initialize_client(self) -> bool:
        try:
            if not all([self.access_key_id, self.secret_access_key, self.bucket_name, self.endpoint_url]):
                logging.warning("YC storage credentials are not fully configured.")
                return False

            self.s3_client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=Config(signature_version="s3v4"),
            )
            # Probe bucket
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            self.initialized = True
            logging.info("Yandex Object Storage client initialized.")
            return True
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code == "404":
                logging.error(f"Bucket {self.bucket_name} not found")
            elif code == "403":
                logging.error("Access to bucket denied. Check credentials/permissions.")
            else:
                logging.error(f"S3 client error during init: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error initializing storage: {e}")
            return False

    async def upload_from_memory(self, file_content: bytes, object_name: str, content_type: str = "application/octet-stream") -> Optional[str]:
        """Upload bytes to object storage and return public URL."""
        try:
            if not self.initialized and not self.initialize_client():
                return None
            if not file_content:
                logging.error("upload_from_memory: empty content")
                return None

            loop = asyncio.get_running_loop()
            file_obj = io.BytesIO(file_content)

            def _put():
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=object_name,
                    Body=file_obj,
                    ContentType=content_type,
                    ACL="public-read",
                )

            await loop.run_in_executor(None, _put)
            url = f"{self.endpoint_url}/{self.bucket_name}/{object_name}".rstrip("/")
            return url
        except Exception as e:
            logging.error(f"upload_from_memory failed: {e}")
            return None

    async def delete_object(self, object_name: str) -> bool:
        try:
            if not self.initialized and not self.initialize_client():
                return False
            loop = asyncio.get_running_loop()

            def _delete():
                self.s3_client.delete_object(Bucket=self.bucket_name, Key=object_name)

            await loop.run_in_executor(None, _delete)
            return True
        except Exception as e:
            logging.error(f"delete_object failed: {e}")
            return False

    async def delete_bouquet_files(self, bouquet_id: str) -> bool:
        """Delete all objects under bouquets/{bouquet_id}/ prefix."""
        try:
            if not self.initialized and not self.initialize_client():
                return False
            prefix = f"bouquets/{bouquet_id}/"
            loop = asyncio.get_running_loop()

            def _list():
                return self.s3_client.list_objects_v2(Bucket=self.bucket_name, Prefix=prefix)

            response = await loop.run_in_executor(None, _list)
            to_delete = [{"Key": c["Key"]} for c in response.get("Contents", [])]
            if not to_delete:
                return True

            def _batch_delete():
                self.s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={"Objects": to_delete, "Quiet": True},
                )

            await loop.run_in_executor(None, _batch_delete)
            return True
        except Exception as e:
            logging.error(f"delete_bouquet_files failed: {e}")
            return False


# Global instance
yandex_storage = YandexObjectStorage()


async def upload_photo_to_storage(bot: Bot, file_id: str, bouquet_id: str, index: int) -> Optional[str]:
    """Download a Telegram photo by file_id and upload to Yandex storage. Returns URL or None."""
    try:
        # Resolve file path
        file = await bot.get_file(file_id)
        if not file:
            logging.error("Telegram get_file returned None")
            return None

        file_path = file.file_path
        # Download bytes
        downloaded = await bot.download_file(file_path)
        file_bytes = downloaded.read() if downloaded else None
        if not file_bytes:
            logging.error("Failed to download photo from Telegram")
            return None

        # Determine extension
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".heic":
            converted = await convert_heic_to_jpeg(file_bytes)
            if not converted:
                logging.error("HEIC conversion failed")
                return None
            file_bytes = converted
            ext = ".jpg"

        # Object key
        unique = uuid.uuid4().hex
        object_name = f"bouquets/{bouquet_id}/{unique}-{index}{ext or '.jpg'}"

        # Content type
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(ext, "image/jpeg")

        url = await yandex_storage.upload_from_memory(file_bytes, object_name, content_type=mime)
        if not url:
            logging.error("Photo upload failed")
        return url
    except Exception as e:
        logging.error(f"upload_photo_to_storage error: {e}", exc_info=True)
        return None


async def upload_video_to_storage(bot: Bot, file_id: str, bouquet_id: str) -> Optional[str]:
    """Download a Telegram video by file_id and upload to Yandex storage. Returns URL or None."""
    try:
        file = await bot.get_file(file_id)
        if not file:
            logging.error("Telegram get_file (video) returned None")
            return None

        file_path = file.file_path
        downloaded = await bot.download_file(file_path)
        file_bytes = downloaded.read() if downloaded else None
        if not file_bytes:
            logging.error("Failed to download video from Telegram")
            return None

        ext = os.path.splitext(file_path)[1].lower() or ".mp4"
        unique = uuid.uuid4().hex
        object_name = f"bouquets/{bouquet_id}/{unique}{ext}"

        url = await yandex_storage.upload_from_memory(file_bytes, object_name, content_type="video/mp4")
        if not url:
            logging.error("Video upload failed")
        return url
    except Exception as e:
        logging.error(f"upload_video_to_storage error: {e}", exc_info=True)
        return None
