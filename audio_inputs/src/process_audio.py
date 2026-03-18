import os
import sys
import time
import uuid
import json
from urllib.parse import urlparse

import boto3

# Read config from environment variables (passed by GitHub Actions)
AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET = os.getenv("S3_BUCKET")
TARGET_LANGUAGE_CODE = os.getenv("TARGET_LANGUAGE_CODE", "es")  # default Spanish
ENV_PREFIX = os.getenv("ENV_PREFIX", "beta")  # "beta" or "prod"

s3_client = boto3.client("s3", region_name=AWS_REGION)
transcribe_client = boto3.client("transcribe", region_name=AWS_REGION)
translate_client = boto3.client("translate", region_name=AWS_REGION)
polly_client = boto3.client("polly", region_name=AWS_REGION)


def upload_audio_to_s3(local_path: str) -> str:
    """
    Uploads local audio file to S3 under ENV_PREFIX/audio_inputs/ and returns the S3 URI.
    """
    file_name = os.path.basename(local_path)
    s3_key = f"{ENV_PREFIX}/audio_inputs/{file_name}"

    print(f"Uploading {local_path} to s3://{S3_BUCKET}/{s3_key}")
    s3_client.upload_file(local_path, S3_BUCKET, s3_key)

    s3_uri = f"s3://{S3_BUCKET}/{s3_key}"
    print(f"Uploaded to {s3_uri}")
    return s3_uri


def start_transcription_job(job_name: str, s3_uri: str) -> str:
    """
    Starts a Transcribe job for an audio file in S3.
    Returns the job name.
    """
    print(f"Starting transcription job {job_name} for {s3_uri}")

    transcribe_client.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": s3_uri},
        MediaFormat="mp3",
        LanguageCode="en-US",
        OutputBucketName=S3_BUCKET,
        OutputKey=f"{ENV_PREFIX}/transcribe_raw/{job_name}/"
    )

    return job_name


def wait_for_transcription(job_name: str, poll_interval: int = 10) -> str:
    """
    Polls Transcribe until the job is completed.
    Returns the S3 key of the transcript JSON file.
    """
    print(f"Waiting for transcription job {job_name} to complete...")
    while True:
        response = transcribe_client.get_transcription_job(
            TranscriptionJobName=job_name
        )
        status = response["TranscriptionJob"]["TranscriptionJobStatus"]
        print(f"Transcription job status: {status}")

        if status == "COMPLETED":
            transcript_uri = response["TranscriptionJob"]["Transcript"]["TranscriptFileUri"]
            print(f"Transcript file URI: {transcript_uri}")
            break
        elif status == "FAILED":
            raise RuntimeError(f"Transcription job {job_name} failed")

        time.sleep(poll_interval)

    # transcript_uri is usually an S3 pre-signed URL or S3 path
    # We'll parse bucket/key if it's an s3:// URI or use HTTP GET for https URLs.
    parsed = urlparse(transcript_uri)
    if parsed.scheme == "s3":
        transcript_bucket = parsed.netloc
        transcript_key = parsed.path.lstrip("/")
        print(f"Transcript stored at s3://{transcript_bucket}/{transcript_key}")
        return transcript_key
    else:
        # If Transcribe wrote to S3 bucket we specified, output key should be known:
        # {ENV_PREFIX}/transcribe_raw/{job_name}/...json
        # We can list objects under that prefix.
        prefix = f"{ENV_PREFIX}/transcribe_raw/{job_name}/"
        resp = s3_client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix)
        contents = resp.get("Contents", [])
        json_keys = [obj["Key"] for obj in contents if obj["Key"].endswith(".json")]
        if not json_keys:
            raise RuntimeError("Could not find transcript JSON in S3")
        transcript_key = json_keys[0]
        print(f"Transcript stored at s3://{S3_BUCKET}/{transcript_key}")
        return transcript_key


def download_transcript_text(transcript_key: str) -> str:
    """
    Downloads the transcript JSON from S3 and returns the transcript text.
    """
    print(f"Downloading transcript JSON from s3://{S3_BUCKET}/{transcript_key}")
    obj = s3_client.get_object(Bucket=S3_BUCKET, Key=transcript_key)
    data = obj["Body"].read().decode("utf-8")
    transcript_json = json.loads(data)
    transcript_text = transcript_json["results"]["transcripts"][0]["transcript"]
    print(f"Transcript text length: {len(transcript_text)} characters")
    return transcript_text


def upload_text_to_s3(text: str, s3_key: str):
    print(f"Uploading text to s3://{S3_BUCKET}/{s3_key}")
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=text.encode("utf-8"),
        ContentType="text/plain"
    )


def translate_text(text: str, target_lang: str) -> str:
    print(f"Translating text to {target_lang}")
    response = translate_client.translate_text(
        Text=text,
        SourceLanguageCode="en",
        TargetLanguageCode=target_lang
    )
    translated_text = response["TranslatedText"]
    print(f"Translated text length: {len(translated_text)} characters")
    return translated_text


def synthesize_speech(text: str, language_code: str, voice_id: str = "Lucia") -> bytes:
    """
    Calls Polly to synthesize speech from text.
    Adjust 'language_code' and 'voice_id' based on your target language.
    """
    print(f"Synthesizing speech with Polly in {language_code}, voice {voice_id}")
    response = polly_client.synthesize_speech(
        Text=text,
        OutputFormat="mp3",
        VoiceId=voice_id,
        LanguageCode=language_code
    )
    audio_stream = response["AudioStream"].read()
    print(f"Synthesized audio size: {len(audio_stream)} bytes")
    return audio_stream


def upload_audio_bytes_to_s3(audio_bytes: bytes, s3_key: str):
    print(f"Uploading synthesized audio to s3://{S3_BUCKET}/{s3_key}")
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=audio_bytes,
        ContentType="audio/mpeg"
    )


def process_single_audio_file(local_audio_path: str):
    """
    End-to-end processing for a single .mp3 file:
    - Upload to S3
    - Transcribe
    - Translate
    - Synthesize speech
    - Upload all artifacts to structured S3 paths
    """
    base_name = os.path.splitext(os.path.basename(local_audio_path))[0]
    job_id = str(uuid.uuid4())[:8]
    transcribe_job_name = f"{ENV_PREFIX}-{base_name}-{job_id}"

    # 1. Upload audio
    audio_s3_uri = upload_audio_to_s3(local_audio_path)

    # 2. Start transcription
    start_transcription_job(transcribe_job_name, audio_s3_uri)

    # 3. Wait for transcription and get transcript key
    transcript_key = wait_for_transcription(transcribe_job_name)

    # 4. Download transcript text
    transcript_text = download_transcript_text(transcript_key)

    # 5. Upload clean transcript text to transcripts folder
    transcript_output_key = f"{ENV_PREFIX}/transcripts/{base_name}.txt"
    upload_text_to_s3(transcript_text, transcript_output_key)

    # 6. Translate transcript
    translated_text = translate_text(transcript_text, TARGET_LANGUAGE_CODE)

    # 7. Upload translation text
    translation_output_key = f"{ENV_PREFIX}/translations/{base_name}_{TARGET_LANGUAGE_CODE}.txt"
    upload_text_to_s3(translated_text, translation_output_key)

    # 8. Synthesize speech from translation
    # Map target language to Polly LanguageCode / VoiceId
    # Example for Spanish (US or Spain); adjust as desired.
    polly_language_code = "es-ES"
    polly_voice_id = "Lucia"

    audio_bytes = synthesize_speech(translated_text, polly_language_code, polly_voice_id)

    # 9. Upload synthesized audio
    audio_output_key = f"{ENV_PREFIX}/audio_outputs/{base_name}_{TARGET_LANGUAGE_CODE}.mp3"
    upload_audio_bytes_to_s3(audio_bytes, audio_output_key)

    print("Processing completed for:", local_audio_path)
    print("Artifacts:")
    print(f"  Transcript:   s3://{S3_BUCKET}/{transcript_output_key}")
    print(f"  Translation:  s3://{S3_BUCKET}/{translation_output_key}")
    print(f"  Audio output: s3://{S3_BUCKET}/{audio_output_key}")


def main():
    # Expect audio files in ./audio_inputs directory by default
    input_dir = os.getenv("AUDIO_INPUT_DIR", "audio_inputs")
    if not os.path.isdir(input_dir):
        print(f"Input directory not found: {input_dir}")
        sys.exit(1)

    audio_files = [
        os.path.join(input_dir, f)
        for f in os.listdir(input_dir)
        if f.lower().endswith(".mp3")
    ]

    if not audio_files:
        print("No .mp3 files found in audio_inputs/. Nothing to process.")
        return

    print(f"Found {len(audio_files)} audio file(s) to process.")
    for audio_path in audio_files:
        process_single_audio_file(audio_path)


if __name__ == "__main__":
    main()