### Multilingual Audio Pipeline (Pixel Learning Co.)

This project implements an automated, multilingual audio transformation pipeline using **Amazon Transcribe**, **Amazon Translate**, **Amazon Polly**, and **Amazon S3**, fully orchestrated with **GitHub Actions**.

---

#### Architecture Overview

1. Content team adds `.mp3` files to the `audio_inputs/` folder.
2. GitHub Actions workflows run a Python script (`src/process_audio.py`) that:
   - Uploads audio to S3
   - Transcribes English speech with Amazon Transcribe
   - Translates transcripts into a target language with Amazon Translate
   - Synthesizes speech in the target language using Amazon Polly
   - Stores transcripts, translations, and generated audio back to S3 under structured prefixes.

Workflows:
- **Pull Request Workflow (`on_pull_request.yml`)**
  - Trigger: Pull Request to `main`
  - Environment prefix: `beta/`
- **Main Branch Workflow (`on_merge.yml`)**
  - Trigger: Push to `main` (e.g., after PR merge)
  - Environment prefix: `prod/`

---

#### S3 Folder Structure

For each environment (`beta` or `prod`):

- `s3://<S3_BUCKET>/<env>/audio_inputs/filename.mp3`
- `s3://<S3_BUCKET>/<env>/transcripts/filename.txt`
- `s3://<S3_BUCKET>/<env>/translations/filename_<lang>.txt`
- `s3://<S3_BUCKET>/<env>/audio_outputs/filename_<lang>.mp3`

Example:
- `s3://pixel-audio-pipeline-bucket/beta/transcripts/lesson1.txt`
- `s3://pixel-audio-pipeline-bucket/prod/audio_outputs/lesson1_es.mp3`

---

#### AWS Setup

1. **Create S3 Bucket**
   - In AWS S3, create a bucket, e.g. `pixel-audio-pipeline-bucket`.
   - Keep it private (block public access).

2. **IAM User & Permissions**
   - Create an IAM user for GitHub Actions (e.g. `github-actions-audio-pipeline`).
   - Grant permissions:
     - `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` on your bucket
     - `transcribe:StartTranscriptionJob`, `transcribe:GetTranscriptionJob`
     - `translate:TranslateText`
     - `polly:SynthesizeSpeech`
   - Generate an **Access Key** (ID + Secret).

3. **Enable Services**
   - Ensure **Transcribe**, **Translate**, and **Polly** are available in your chosen AWS region (e.g. `us-east-1`).

---

#### GitHub Secrets Configuration

In your GitHub repo:

1. Go to **Settings → Secrets and variables → Actions**.
2. Add the following repository secrets:

- `AWS_ACCESS_KEY_ID`: IAM user access key ID
- `AWS_SECRET_ACCESS_KEY`: IAM user secret access key
- `AWS_REGION`: e.g. `us-east-1`
- `S3_BUCKET`: e.g. `pixel-audio-pipeline-bucket`

These are injected into workflows as environment variables and never stored in code.

---

#### How to Use the Pipeline

1. **Add Audio Files**
   - Place one or more `.mp3` files in the `audio_inputs/` directory.
   - Example: `audio_inputs/lesson1.mp3`

2. **Create a Feature Branch**
   - From `main`, create a branch, e.g. `feature/add-lesson1-audio`.
   - Commit and push your changes.

3. **Open a Pull Request**
   - Open a PR from your feature branch into `main`.
   - This triggers the **PR Workflow** (`on_pull_request.yml`).
   - The workflow:
     - Installs Python dependencies
     - Runs `src/process_audio.py`
     - Uses `ENV_PREFIX=beta`, so outputs are stored under `beta/` in S3.

4. **Verify Beta Outputs in S3**
   - In AWS S3 console, navigate to:
     - `s3://<S3_BUCKET>/beta/transcripts/lesson1.txt`
     - `s3://<S3_BUCKET>/beta/translations/lesson1_es.txt`
     - `s3://<S3_BUCKET>/beta/audio_outputs/lesson1_es.mp3`
   - Download and review files for content and quality.

5. **Merge to Main (Production)**
   - After reviewing in `beta`, merge the PR into `main`.
   - This triggers the **Main Workflow** (`on_merge.yml`).
   - The workflow runs the same script with `ENV_PREFIX=prod`, producing:
     - `s3://<S3_BUCKET>/prod/transcripts/lesson1.txt`
     - `s3://<S3_BUCKET>/prod/translations/lesson1_es.txt`
     - `s3://<S3_BUCKET>/prod/audio_outputs/lesson1_es.mp3`

6. **Change Target Language (Optional)**
   - The environment variable `TARGET_LANGUAGE_CODE` controls the translation language (ISO code).
   - Default is `es` (Spanish) in both workflows.
   - To add more languages or switch to another (e.g., French `fr`), update the workflows and adjust the Polly language/voice mapping in `process_audio.py`.

---

#### Local Testing (Optional, for Developers)

1. Create and activate a virtual environment:
   ```bash
   cd src
   python -m venv .venv
   source .venv/bin/activate  # on Windows: .venv\Scripts\activate
   pip install -r requirements.txt