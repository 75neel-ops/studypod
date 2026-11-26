# StudyPod — Built & Owned by NilanjanC

StudyPod is a mobile-friendly group-study accountability MVP built with Streamlit, MongoDB Atlas, Google Gemini and Razorpay.

## Features

- Student registration and login (bcrypt password hashing).
- Create study pods for Class 9–12, CBSE, ICSE/ISC and West Bengal boards.
- Board/class/subject-aware chapter suggestions using Gemini, with manual chapter entry.
- Personal weekly sprint schedule that respects each student's Monday–Sunday available study hours, including zero-hour days.
- Invite-code joining with a maximum of five members per pod.
- Weekly milestones, proof-of-work submission (text, link or file), and a server-side vault gate.
- Knowledge-gap agenda: 15-minute peer teaching, 30-minute group blindspot practice, and mastered-topic skip decisions.
- Optional Razorpay Checkout donations (₹50, ₹100, ₹250).

## Deploy on Streamlit Community Cloud

1. Push this repository to GitHub.
2. Open https://share.streamlit.io and sign in with GitHub.
3. Create an app from repository `75neel-ops/studypod`, branch `main`, main file `app.py`.
4. In the app's **Settings → Secrets**, add the secrets shown below.
5. Deploy.

## Streamlit Secrets

Add this TOML in Streamlit Community Cloud → App → Settings → Secrets. Do not commit secrets to GitHub.

```toml
[mongodb]
uri = "mongodb+srv://studypod_app:URL_ENCODED_PASSWORD@YOUR_CLUSTER.mongodb.net/?retryWrites=true&w=majority"
database = "studypod"

[app]
owner = "NilanjanC"
session_secret = "REPLACE_WITH_A_LONG_RANDOM_SECRET"

[gemini]
api_key = "YOUR_GEMINI_API_KEY"
model = "gemini-3.5-flash-lite"

[razorpay]
key_id = "YOUR_RAZORPAY_KEY_ID"
key_secret = "YOUR_RAZORPAY_KEY_SECRET"
me_link = "https://razorpay.me/@YOUR_HANDLE"
```

Use the password for the restricted MongoDB user `studypod_app`, not the Atlas administrator. URL-encode special characters in the password. The database user should have only `readWrite` on `studypod`.

## MongoDB Network Access

Streamlit Community Cloud does not provide one fixed outbound IP for every deployment. For an MVP, Atlas Network Access may need an IP access entry of `0.0.0.0/0` so Streamlit can connect. This allows network-level access from any IP, so use a long unique database password, the database-scoped `readWrite@studypod` user, TLS (enabled by the MongoDB SRV connection), and never expose the URI. For a production deployment, move to a host with fixed egress IPs or a private networking solution and narrow the allowlist.

## Important deployment notes

- MongoDB Atlas is the persistent database. Uploaded proof files are stored in MongoDB GridFS; keep files small (maximum 5 MB per upload) and monitor the Atlas 512 MB free-tier limit.
- Gemini is optional. Without a Gemini key, chapter suggestions and sprint generation use deterministic fallbacks.
- Razorpay is optional. Without live credentials, the app shows the configured Razorpay.me fallback link if supplied.
- Razorpay live Checkout requires a valid Key ID and Key Secret. Payment signatures are verified by the app after Checkout returns.
- This is an MVP, not a finished school-grade identity system. Students register with a name and password; add email verification, parental consent and stronger moderation before a public school launch.
- StudyPod is intended for study coordination. Do not upload sensitive personal information.

## Local run (optional)

Python 3.11+:
```bash
pip install -r requirements.txt
streamlit run app.py
``

For local testing, create `.streamlit/secrets.toml` using the same TOML structure above. That file is ignored by Git.

---

**Built & Owned by NilanjanC**
