from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import date, timedelta
from urllib.parse import quote

import streamlit as st
import streamlit.components.v1 as components
from bson import ObjectId

import database as db
from planner import generate_sprint, suggest_chapters, rebalance_schedule

st.set_page_config(page_title="StudyPod | NilanjanC", page_icon="📚", layout="wide")

st.markdown("""
<style>
  .block-container {max-width: 1120px; padding-top: 1.5rem; padding-bottom: 3rem;}
  .hero {background: linear-gradient(120deg,#202d66,#596fe0); color:white; padding:1.5rem 1.7rem; border-radius:20px; margin-bottom:1rem;}
  .hero h1 {color:white; margin:0; font-size:2.25rem;}
  .hero p {color:#e7eaff; margin:.35rem 0 0 0;}
  .owner {font-size:.82rem; color:#718096;}
  .card {background:white; border:1px solid #e6e9f2; border-radius:16px; padding:1rem 1.1rem; margin:.35rem 0;}
  .small-muted {color:#64748b; font-size:.88rem;}
  div.stButton > button {border-radius:10px;}
  [data-testid="stMetric"] {background:#fff; border:1px solid #e6e9f2; padding:12px; border-radius:12px;}
</style>
""", unsafe_allow_html=True)


def secret_section(name: str):
    try:
        return st.secrets.get(name, {})
    except Exception:
        return {}


def make_invite_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(7))


def subjects_for(class_name: str, board: str) -> list[str]:
    if class_name in ("Class 9", "Class 10"):
        if "West Bengal" in board:
            return ["Mathematics", "Physical Science", "Life Science", "History", "Geography", "English", "Bengali", "Computer Applications"]
        return ["Mathematics", "Science", "Physics", "Chemistry", "Biology", "History", "Geography", "English", "Computer Applications"]
    if class_name in ("Class 11", "Class 12"):
        return ["Mathematics", "Physics", "Chemistry", "Biology", "Accountancy", "Business Studies", "Economics", "History", "Geography", "Political Science", "Computer Science", "English"]
    return ["Mathematics", "Science", "English"]


def require_login() -> bool:
    if st.session_state.get("user"):
        return True
    st.markdown('<div class="hero"><h1>📚 StudyPod</h1><p>Study together. Stay accountable. Reach your goals.</p></div>', unsafe_allow_html=True)
    login_tab, register_tab = st.tabs(["Log in", "Create student account"])
    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", use_container_width=True)
        if submitted:
            user = db.authenticate(username, password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("Username or password is incorrect.")
    with register_tab:
        with st.form("register_form"):
            display_name = st.text_input("Your name")
            new_username = st.text_input("Create a username (letters, numbers and underscores)")
            new_password = st.text_input("Create a password (at least 8 characters)", type="password")
            confirm = st.text_input("Confirm password", type="password")
            accepted = st.checkbox("I will use StudyPod respectfully and avoid sharing sensitive personal information.")
            create = st.form_submit_button("Create account", use_container_width=True)
        if create:
            clean_user = new_username.strip().lower()
            if len(display_name.strip()) < 2:
                st.error("Please enter your name.")
            elif len(clean_user) < 3 or not clean_user.replace("_", "").isalnum():
                st.error("Username must be at least 3 characters and contain only letters, numbers or underscores.")
            elif len(new_password) < 8:
                st.error("Use a password of at least 8 characters.")
            elif new_password != confirm:
                st.error("The passwords do not match.")
            elif not accepted:
                st.error("Please accept the student-use statement.")
            else:
                try:
                    db.create_user(clean_user, display_name, new_password)
                    st.success("Account created. Please log in.")
                except Exception:
                    st.error("That username may already be in use. Try another.")
    st.markdown('<p class="owner">Built &amp; Owned by NilanjanC</p>', unsafe_allow_html=True)
    return False


def show_donation():
    st.markdown("---")
    st.markdown("##### Satisfied? Fuel the Dev")
    st.caption("If StudyPod helped your group, you can support its development.")
    rzp = secret_section("razorpay")
    key_id = rzp.get("key_id", "")
    key_secret = rzp.get("key_secret", "")
    me_link = rzp.get("me_link", "")
    amount = st.radio("Choose a contribution", [50, 100, 250], horizontal=True, format_func=lambda x: f"₹{x}")
    if key_id and key_secret and not str(key_id).lower().startswith("your_"):
        if st.button("Support NilanjanC via Razorpay", key="donate_checkout"):
            try:
                import razorpay
                client = razorpay.Client(auth=(key_id, key_secret))
                order = client.order.create({
                    "amount": int(amount) * 100,
                    "currency": "INR",
                    "receipt": f"studypod_{secrets.token_hex(5)}",
                    "notes": {"purpose": "Voluntary StudyPod development support"},
                })
                st.session_state.rzp_order = {
                    "id": order["id"], "amount": int(amount), "key_id": key_id,
                }
                st.rerun()
            except Exception as exc:
                st.error(f"Razorpay could not create an order: {exc}")
    elif me_link:
        st.link_button("Support NilanjanC via Razorpay", me_link, use_container_width=False)
        st.caption("The Razorpay payment page may ask you to enter the amount.")
    else:
        st.caption("Razorpay support will be enabled after the owner adds payment credentials.")

    order = st.session_state.get("rzp_order")
    if order:
        checkout_html = f"""
        <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
        <div style="font-family:Arial;padding:8px">
          <p>Ready to contribute ₹{order['amount']}?</p>
          <button id="rzp-open" style="background:#5267d8;color:white;border:0;padding:12px 18px;border-radius:9px;font-weight:600;cursor:pointer">Open secure Razorpay Checkout</button>
        </div>
        <script>
          const options = {{
            key: {json.dumps(order['key_id'])},
            amount: {order['amount'] * 100},
            currency: "INR",
            name: "StudyPod",
            description: "Voluntary development support",
            order_id: {json.dumps(order['id'])},
            handler: function (response) {{
              const q = new URLSearchParams({{
                rzp_payment_id: response.razorpay_payment_id,
                rzp_order_id: response.razorpay_order_id,
                rzp_signature: response.razorpay_signature
              }});
              window.parent.location.href = window.parent.location.pathname + "?" + q.toString();
            }},
            theme: {{color: "#5267d8"}}
          }};
          document.getElementById("rzp-open").onclick = function() {{
            const checkout = new Razorpay(options);
            checkout.open();
          }};
        </script>
        """
        components.html(checkout_html, height=100)
        st.caption("Checkout is handled by Razorpay. Do not share payment credentials.")

    # Verify Checkout callback after Razorpay redirects back to the app.
    params = st.query_params
    payment_id = params.get("rzp_payment_id")
    order_id = params.get("rzp_order_id")
    signature = params.get("rzp_signature")
    if payment_id and order_id and signature and key_secret:
        expected = hmac.new(
            str(key_secret).encode(),
            f"{order_id}|{payment_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected, str(signature)):
            st.success("Thank you! Razorpay payment signature verified.")
        else:
            st.error("We could not verify the Razorpay payment signature. Please contact support.")
        for key in ("rzp_payment_id", "rzp_order_id", "rzp_signature"):
            if key in st.query_params:
                del st.query_params[key]
        st.session_state.pop("rzp_order", None)


def create_pod_ui(user):
    st.subheader("Create a StudyPod")
    st.caption("Add each subject, its exam chapters, and any homework or projects with deadlines. Set your total daily study hours only in Master timetable.")
    class_col, board_col, subject_col = st.columns(3)
    with class_col:
        class_name = st.selectbox("Class", ["Class 9", "Class 10", "Class 11", "Class 12"], key="new_class")
    with board_col:
        board = st.selectbox("Board", ["CBSE", "ICSE / ISC", "West Bengal Board (WBBSE / WBCHSE)"], key="new_board")
    with subject_col:
        subject = st.selectbox("Subject", subjects_for(class_name, board), key="new_subject")

    catalogue_context = f"{class_name}|{board}|{subject}"
    if st.session_state.get("chapter_catalogue_context") != catalogue_context:
        st.session_state.suggested_chapters = []
        st.session_state.selected_exam_chapters = []
        st.session_state.chapter_catalogue_context = catalogue_context

    suggest_col, clear_col = st.columns([1, 1])
    with suggest_col:
        if st.button("📚 Load chapter list", key="suggest_chapters"):
            with st.spinner("Preparing the chapter list for your selected class and subject..."):
                suggestions = suggest_chapters(class_name, board, subject)
            if suggestions:
                st.session_state.suggested_chapters = suggestions
                st.session_state.selected_exam_chapters = []
                st.success("Chapter list loaded. Now choose the chapters included in your examination.")
            else:
                st.warning("The chapter list could not be loaded. Check that your Gemini API key is configured, or add chapters manually below.")
    with clear_col:
        if st.button("Clear chapter list", key="clear_suggestions"):
            st.session_state.suggested_chapters = []
            st.session_state.selected_exam_chapters = []
            st.rerun()

    suggestions = st.session_state.get("suggested_chapters", [])
    if suggestions:
        selected_chapters = st.multiselect(
            "Choose the chapters for this examination",
            options=suggestions,
            default=st.session_state.get("selected_exam_chapters", []),
            key="selected_exam_chapters",
            placeholder="Click here and select one or more chapters",
            help="You can select all the chapters you need. Click the box again to add more.",
        )
        st.caption(f"{len(selected_chapters)} chapter(s) selected.")
    else:
        selected_chapters = []
        st.info("First click **Load chapter list**. You will then be able to select chapters from a dropdown.")
    with st.expander("➕ Add a chapter manually (if it is missing from the list)"):
        extra_chapters_text = st.text_area(
            "Additional chapter names (one per line)",
            height=90,
            key="extra_chapter_names",
            placeholder="Only use this if a chapter is missing from the suggested list.",
        )
        extra_chapters = [x.strip() for x in extra_chapters_text.splitlines() if x.strip()]

    with st.form("create_pod_form"):
        pod_name = st.text_input("Pod name", placeholder="e.g. Class 10 Maths Sprint")
        date_col, marks_col = st.columns(2)
        with date_col:
            exam_date = st.date_input("Exam date", value=date.today() + timedelta(days=45), min_value=date.today())
        with marks_col:
            total_marks = st.selectbox("Total marks", [40, 50, 70, 80, 90, 100], index=3)
        st.markdown("**Projects and homework (optional)**")
        st.caption("Enter one item per line in this format: Task title | YYYY-MM-DD | estimated hours. Example: Physics model | 2026-12-10 | 3")
        project_text = st.text_area(
            "Projects",
            key="pod_projects_text",
            height=90,
            placeholder="Science model | 2026-12-10 | 3",
        )
        homework_text = st.text_area(
            "Homework",
            key="pod_homework_text",
            height=90,
            placeholder="Maths exercise 5 | 2026-12-02 | 1.5",
        )
        syllabus_file = st.file_uploader("Reference syllabus PDF or image (optional — upload an exam/assignment routine in Master timetable for automatic reading)", type=["pdf", "png", "jpg", "jpeg", "webp"], key="syllabus_upload")
        submitted = st.form_submit_button("Create my subject StudyPod", type="primary", use_container_width=True)

    if submitted:
        chapters = list(dict.fromkeys(
            [x.strip() for x in selected_chapters if x.strip()]
            + [x.strip() for x in extra_chapters if x.strip()]
        ))
        if not pod_name.strip():
            st.error("Please enter a pod name.")
            return
        if not chapters or len(chapters) > 30:
            st.error("Please select at least one chapter from the dropdown or add one manually. A maximum of 30 chapters is allowed.")
            return
        existing = db.get_user_pods(user["username"])
        duplicate = next((
            p for p in existing
            if p.get("owner_username") == user["username"]
            and p.get("name", "").strip().casefold() == pod_name.strip().casefold()
            and p.get("class_name") == class_name
            and p.get("board") == board
            and p.get("subject") == subject
            and p.get("exam_date") == exam_date.isoformat()
        ), None)
        if duplicate:
            st.error("You already own a StudyPod with this name, class, board, subject and exam date. Open the existing pod instead of creating a duplicate.")
            return
        def parse_deadline_items(raw_text, item_type):
            parsed = []
            for line_no, line in enumerate(raw_text.splitlines(), 1):
                if not line.strip():
                    continue
                parts = [part.strip() for part in line.split("|")]
                if len(parts) < 2:
                    st.error(f"{item_type}, line {line_no}: use Title | YYYY-MM-DD | estimated hours")
                    return None
                try:
                    due = date.fromisoformat(parts[1])
                    estimate = float(parts[2]) if len(parts) > 2 and parts[2] else 1.0
                    if estimate <= 0 or estimate > 100:
                        raise ValueError()
                except ValueError:
                    st.error(f"{item_type}, line {line_no}: enter a valid date (YYYY-MM-DD) and hours greater than 0.")
                    return None
                parsed.append({
                    "title": parts[0][:140],
                    "due_date": due.isoformat(),
                    "estimated_hours": estimate,
                    "subject": subject,
                    "type": item_type,
                    "done": False,
                })
            return parsed

        projects = parse_deadline_items(project_text, "Project")
        homeworks = parse_deadline_items(homework_text, "Homework")
        if projects is None or homeworks is None:
            return
        if any(date.fromisoformat(item["due_date"]) < date.today() for item in projects + homeworks):
            st.error("Project and homework deadlines must be today or in the future.")
            return
        # Group milestones remain available for StudyPod collaboration. Personal daily
        # capacity is deliberately configured only once in Master timetable.
        no_daily_capacity = {day: 0.0 for day in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]}
        with st.spinner("Creating your subject StudyPod..."):
            plan, source = generate_sprint(chapters, exam_date, no_daily_capacity, class_name, board, subject, total_marks)
            syllabus_id = db.store_upload(syllabus_file, user["username"], "syllabus") if syllabus_file else None
            pod_doc = {
                "name": pod_name.strip()[:80],
                "owner_username": user["username"],
                "owner_name": user["display_name"],
                "class_name": class_name,
                "board": board,
                "subject": subject,
                "chapters": chapters,
                "exam_date": exam_date.isoformat(),
                "total_marks": int(total_marks),
                "daily_hours": {},
                "projects": projects,
                "homeworks": homeworks,
                "syllabus_file_id": syllabus_id,
                "invite_code": make_invite_code(),
                "created_at": db.utcnow(),
                "planner_source": source,
            }
            pod_id = ObjectId(db.create_pod_document(pod_doc))
            db.add_member(pod_id, user["username"], user["display_name"], "owner")
            db.create_milestones(pod_id, [week.model_dump() for week in plan.weeks])
        st.success(f"StudyPod created! Invite code: {pod_doc['invite_code']}")
        st.info(f"Subject pod created. Share the invite code with up to four other students. Daily study hours will be set in Master timetable.")
        st.session_state.active_pod_id = str(pod_id)
        st.rerun()


def join_pod_ui(user):
    st.subheader("Join an existing StudyPod")
    with st.form("join_pod_form"):
        code = st.text_input("Invite code", max_chars=12).strip().upper()
        join = st.form_submit_button("Join pod", use_container_width=True)
    if join:
        pod = db.get_pod_by_code(code)
        if not pod:
            st.error("That invite code was not found.")
        elif db.is_member(pod["_id"], user["username"]):
            st.session_state.active_pod_id = str(pod["_id"])
            st.rerun()
        elif db.member_count(pod["_id"]) >= 5:
            st.error("This StudyPod is full. A pod can have a maximum of five students.")
        else:
            db.add_member(pod["_id"], user["username"], user["display_name"])
            st.session_state.active_pod_id = str(pod["_id"])
            st.success("You joined the StudyPod.")
            st.rerun()


def practice_questions(subject: str, chapters: list[str], board: str, class_name: str) -> str:
    cfg = secret_section("gemini")
    api_key = cfg.get("api_key", "")
    if api_key:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            model = cfg.get("model", "gemini-3.5-flash-lite")
            response = client.models.generate_content(
                model=model,
                contents=(
                    f"Create 8 original board-style practice questions for {class_name}, {board}, {subject}. "
                    f"Cover only these topics: {', '.join(chapters)}. Mix conceptual, short-answer and application questions. "
                    "Do not reproduce copyrighted past-paper text. Include a concise answer key after the questions."
                ),
            )
            return response.text or "AI could not generate questions."
        except Exception as exc:
            st.warning(f"Gemini is unavailable; showing a simple practice prompt instead. ({str(exc)[:100]})")
    return "\n".join([f"{i+1}. Write a clear explanation and solve one board-style problem from **{topic}**." for i, topic in enumerate(chapters[:8])])


def render_agenda(milestone, members):
    ratings = db.get_confidence(milestone["_id"])
    member_names = {m["username"]: m["display_name"] for m in members}
    by_topic: dict[str, dict[str, int]] = {}
    for item in ratings:
        by_topic.setdefault(item["chapter"], {})[item["username"]] = int(item["score"])
    topics = milestone.get("topics", [])
    if not topics:
        st.info("No topics are attached to this sprint week.")
        return
    st.markdown("### Knowledge-gap agenda")
    for topic in topics:
        scores = by_topic.get(topic, {})
        st.markdown(f"**{topic}**")
        if not scores:
            st.caption("Waiting for confidence ratings.")
            continue
        average = sum(scores.values()) / len(scores)
        everyone_rated = len(scores) == len(members)
        everyone_mastered = everyone_rated and all(value >= 4 for value in scores.values())
        if everyone_mastered:
            st.success("Mastered — Skip in live session.")
        elif everyone_rated and average < 3.0:
            st.warning(f"Group blindspot — schedule a 30-minute collaborative past-paper solving block (average {average:.1f}/5).")
        else:
            st.caption(f"Group confidence average: {average:.1f}/5")
        pairs = []
        for learner, low_score in scores.items():
            if low_score <= 2:
                for teacher, high_score in scores.items():
                    if teacher != learner and high_score >= 4:
                        pairs.append((member_names.get(teacher, teacher), member_names.get(learner, learner)))
        for teacher, learner in pairs:
            st.info(f"Peer teaching: {teacher} teaches {learner} for 15 minutes.")
        if not pairs and not (everyone_rated and average < 3.0) and not everyone_mastered:
            st.caption("No peer-teaching match yet. More ratings may reveal one.")


def open_pod_ui(user, pod_id_text: str):
    pod_id = ObjectId(pod_id_text)
    pod = db.get_db().pods.find_one({"_id": pod_id})
    if not pod or not db.is_member(pod_id, user["username"]):
        st.error("This StudyPod is unavailable or you are not a member.")
        return
    members = db.get_members(pod_id)
    st.markdown(f"## 👥 {pod['name']}")
    st.caption(f"{pod['class_name']} · {pod['board']} · {pod['subject']} · Exam {pod['exam_date']} · {pod['total_marks']} marks")
    metric_cols = st.columns(3)
    metric_cols[0].metric("Pod members", f"{len(members)}/5")
    metric_cols[1].metric("Chapters", len(pod.get("chapters", [])))
    metric_cols[2].metric("Invite code", pod["invite_code"])
    with st.expander("Pod details and members"):
        st.write("**Members:** " + ", ".join(m["display_name"] for m in members))
        st.write("**Chapters:** " + ", ".join(pod.get("chapters", [])))
        for label, key in [("Projects", "projects"), ("Homework", "homeworks")]:
            items = pod.get(key, [])
            if items:
                st.write(f"**{label}:**")
                for item in items:
                    st.write(f"• {item['title']} — due {item['due_date']} · {item['estimated_hours']:g} h")
        if pod.get("syllabus_file_id"):
            try:
                raw, metadata = db.read_upload(pod["syllabus_file_id"])
                st.download_button("Download uploaded syllabus / routine", raw, file_name="pod_syllabus", mime=metadata.get("content_type", "application/octet-stream"))
            except Exception:
                st.caption("The optional syllabus upload could not be loaded.")
    milestones = db.get_milestones(pod_id)
    if not milestones:
        st.info("No sprint milestones were generated.")
        return
    milestone_labels = {
        f"Week {m['week_number']} · {m['start_date']} to {m['end_date']} — {m['title']}": str(m["_id"])
        for m in milestones
    }
    selected_label = st.selectbox("Choose sprint week", list(milestone_labels.keys()))
    milestone_id = milestone_labels[selected_label]
    milestone = db.get_milestone(milestone_id)
    tabs = st.tabs(["1 · Subject overview", "2 · Proof of work", "3 · Group vault", "4 · Confidence & agenda"])

    with tabs[0]:
        st.markdown(f"### {milestone.get('title', 'Weekly sprint')}")
        st.write("Topics: " + ", ".join(milestone.get("topics", [])))
        st.write("**Group learning goals**")
        for task in milestone.get("tasks", []):
            st.write("• " + task)
        st.info("Your personal day-by-day study routine is now managed centrally in **Master timetable**. This StudyPod page is for subject chapters, group accountability, proof of work and peer learning.")
    with tabs[1]:
        st.markdown("### Submit your pre-work")
        st.caption("Submit a solved-question photo/PDF, a written summary, or a link before opening the shared vault.")
        existing = db.get_proof(milestone_id, user["username"])
        if existing:
            st.success("Your proof of work is submitted. The group vault is unlocked for this week.")
            st.caption(f"Last submitted: {existing.get('submitted_at', '').strftime('%d %b %Y, %I:%M %p') if hasattr(existing.get('submitted_at', ''), 'strftime') else 'Submitted'}")
        with st.form(f"proof_form_{milestone_id}"):
            proof_text = st.text_area("Short summary / what you completed", placeholder="I solved questions 1–10 and revised the key formulas...")
            proof_link = st.text_input("Optional link (e.g. a shared audio recording)")
            proof_file = st.file_uploader("Optional proof file (photo, PDF or audio)", type=["png", "jpg", "jpeg", "webp", "pdf", "mp3", "m4a", "wav"], key=f"proof_file_{milestone_id}")
            proof_submit = st.form_submit_button("Submit proof and unlock vault", type="primary")
        if proof_submit:
            if not proof_text.strip() and not proof_link.strip() and not proof_file:
                st.error("Submit at least a short summary, a link or a file.")
            else:
                file_id = db.store_upload(proof_file, user["username"], "proof") if proof_file else None
                db.submit_proof(milestone_id, user["username"], {
                    "text": proof_text.strip()[:5000],
                    "link": proof_link.strip()[:1000],
                    "file_id": file_id,
                    "file_name": proof_file.name if proof_file else None,
                })
                st.success("Proof submitted. Your group vault is now unlocked.")
                st.rerun()
        if existing and existing.get("file_id"):
            try:
                raw, metadata = db.read_upload(existing["file_id"])
                st.download_button("Download your submitted proof", raw, file_name=existing.get("file_name") or "proof", mime=metadata.get("content_type", "application/octet-stream"))
            except Exception:
                st.caption("Your proof file could not be loaded.")

    with tabs[2]:
        if not db.has_proof(milestone_id, user["username"]):
            st.error("🔒 Vault locked. Submit your proof of work for this sprint week first.")
            st.info("The server checks your submission before showing shared notes or AI practice questions.")
        else:
            st.success("🔓 Proof verified — group vault unlocked.")
            notes = st.text_area("Shared group notes", value=milestone.get("vault_notes", ""), height=180, key=f"vault_notes_{milestone_id}")
            if st.button("Save shared notes", key=f"save_notes_{milestone_id}"):
                db.save_vault_notes(milestone["_id"], notes)
                st.success("Shared notes saved for the pod.")
                st.rerun()
            if st.button("Generate board-pattern practice questions", key=f"questions_{milestone_id}"):
                with st.spinner("Preparing practice questions..."):
                    questions = practice_questions(pod["subject"], milestone.get("topics", []), pod["board"], pod["class_name"])
                db.get_db().milestones.update_one({"_id": milestone["_id"]}, {"$set": {"practice_questions": questions}})
                st.rerun()
            refreshed = db.get_milestone(milestone_id)
            if refreshed.get("practice_questions"):
                st.markdown("### Board-pattern practice")
                st.markdown(refreshed["practice_questions"])

    with tabs[3]:
        st.markdown("### Rate your confidence")
        st.caption("Rate each topic from 1 (not confident) to 5 (can teach it).")
        with st.form(f"confidence_form_{milestone_id}"):
            current_ratings = {
                x["chapter"]: x["score"]
                for x in db.get_confidence(milestone["_id"])
                if x["username"] == user["username"]
            }
            selected_scores = {}
            for idx, topic in enumerate(milestone.get("topics", [])):
                selected_scores[topic] = st.select_slider(
                    topic, options=[1, 2, 3, 4, 5],
                    value=int(current_ratings.get(topic, 3)),
                    key=f"confidence_{milestone_id}_{idx}",
                )
            rating_submit = st.form_submit_button("Save my confidence ratings", type="primary")
        if rating_submit:
            for topic, score in selected_scores.items():
                db.save_confidence(milestone["_id"], user["username"], topic, score)
            st.success("Your confidence ratings have been saved.")
            st.rerun()
        render_agenda(milestone, members)



def master_timetable_ui(user):
    st.subheader("🗓️ My Master Study Timetable")
    st.caption("One daily time budget for exams, projects and homework across all selected subjects.")
    all_pods = db.get_user_pods(user["username"])
    if not all_pods:
        st.info("Create or join at least one subject StudyPod first.")
        return

    labels = {f"{p['name']} · {p['subject']} · Exam {p['exam_date']}": str(p["_id"]) for p in all_pods}
    selected_labels = st.multiselect(
        "Choose the subjects / StudyPods",
        options=list(labels.keys()),
        default=list(labels.keys()),
        key="master_selected_pods",
    )
    selected_ids = [labels[label] for label in selected_labels]
    selected_pods = [p for p in all_pods if str(p["_id"]) in selected_ids]
    if not selected_pods:
        st.warning("Select at least one subject StudyPod.")
        return

    st.markdown("### Your total available study time")
    st.caption("Enter the total time you can study each day. StudyPod will divide it between subjects, revision, projects and homework.")
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    defaults = [3.0, 3.0, 3.0, 3.0, 3.0, 5.0, 5.0]
    hours = {}
    cols = st.columns(4)
    for i, day in enumerate(day_names):
        with cols[i % 4]:
            hours[day.lower()] = st.number_input(
                day, min_value=0.0, max_value=16.0, value=defaults[i],
                step=0.5, key=f"master_hours_{day.lower()}",
            )
    weekly_hours = sum(hours.values())
    st.metric("Total available hours per week", f"{weekly_hours:g} h")
    prior_master = db.get_master_timetable(user["username"]) or {}
    imported_subjects = [item.get("subject", "") for item in prior_master.get("imported_exams", []) if item.get("subject")]
    weak_subjects = st.multiselect(
        "Which subjects are you weak in? (StudyPod will give these extra time)",
        options=sorted(set([p["subject"] for p in selected_pods] + imported_subjects)),
        key="master_weak_subjects",
        help="Choose honestly. Weak subjects receive extra practice and revision sessions.",
    )

    st.markdown("### Add your school work")
    st.caption("You can add deadlines here, or enter projects and homework inside each subject's Create Pod section.")
    with st.expander("➕ Add an extra project or homework"):
        with st.form("master_add_assignment_form"):
            assignment_type = st.selectbox("Type", ["Project", "Homework"])
            assignment_title = st.text_input("Title")
            available_assignment_subjects = set()
            for pod in selected_pods:
                available_assignment_subjects.update(subjects_for(pod.get("class_name", "Class 10"), pod.get("board", "CBSE")))
                available_assignment_subjects.add(pod.get("subject", ""))
            available_assignment_subjects.update(item.get("subject", "") for item in prior_master.get("imported_exams", []) if item.get("subject"))
            available_assignment_subjects.discard("")
            assignment_subject = st.selectbox("Subject", sorted(available_assignment_subjects))
            assignment_due = st.date_input("Submission date", value=date.today() + timedelta(days=7), min_value=date.today())
            assignment_hours = st.number_input("Estimated work hours", min_value=0.5, max_value=100.0, value=2.0, step=0.5)
            add_assignment = st.form_submit_button("Add to my timetable")
        if add_assignment:
            if not assignment_title.strip():
                st.error("Please enter a title.")
            else:
                saved_now = db.get_master_timetable(user["username"]) or {}
                assignments = list(saved_now.get("extra_assignments", []))
                assignments.append({
                    "id": secrets.token_hex(8), "type": assignment_type,
                    "title": assignment_title.strip()[:140], "subject": assignment_subject,
                    "due_date": assignment_due.isoformat(), "estimated_hours": float(assignment_hours),
                    "done": False,
                })
                db.save_master_timetable(user["username"], {"extra_assignments": assignments})
                st.success("Deadline task added.")
                st.rerun()

    st.markdown("### Import your exam and assignment routine")
    st.caption("Upload a photo or PDF of a handwritten/printed routine. Gemini will extract exam dates, subjects, chapters, projects and homework. Review the extracted details before using them.")
    uploaded_plan = st.file_uploader(
        "Upload exam routine / handwritten task list",
        type=["pdf", "png", "jpg", "jpeg", "webp"],
        key="master_plan_upload",
    )
    if uploaded_plan and st.button("🔎 Read my uploaded routine", key="parse_master_upload"):
        cfg = secret_section("gemini")
        api_key = cfg.get("api_key", "")
        if not api_key:
            st.error("Gemini API key is not configured. You can still enter tasks manually.")
        else:
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=api_key)
                prompt = """Read this student's uploaded exam/assignment paper. Extract only information clearly visible.
Return valid JSON with this shape:
{
 "exams":[{"subject":"Mathematics","exam_date":"YYYY-MM-DD","chapters":["Chapter 1"]}],
 "assignments":[{"type":"Project or Homework","title":"Task title","subject":"Subject or blank","due_date":"YYYY-MM-DD","estimated_hours":2}]
}
Use an empty array when absent. Do not guess missing dates or subjects. Use null for an unreadable date. Estimated hours may be a sensible estimate only when the task is clear; otherwise use 1.0. Dates must be full dates; if the year is not visible, use null."""
                part = types.Part.from_bytes(data=uploaded_plan.getvalue(), mime_type=uploaded_plan.type or "application/pdf")
                response = client.models.generate_content(
                    model=cfg.get("model", "gemini-3.5-flash-lite"),
                    contents=[prompt, part],
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1),
                )
                extracted = json.loads(response.text or "{}")
                clean_exams = []
                for item in extracted.get("exams", []):
                    try:
                        exam_day = date.fromisoformat(str(item.get("exam_date", "")))
                    except ValueError:
                        continue
                    subject = str(item.get("subject", "")).strip()
                    if subject:
                        clean_exams.append({
                            "subject": subject,
                            "exam_date": exam_day.isoformat(),
                            "chapters": [str(x).strip() for x in item.get("chapters", []) if str(x).strip()][:40],
                        })
                clean_assignments = []
                for item in extracted.get("assignments", []):
                    try:
                        due = date.fromisoformat(str(item.get("due_date", "")))
                    except ValueError:
                        continue
                    title = str(item.get("title", "")).strip()
                    if title:
                        clean_assignments.append({
                            "id": secrets.token_hex(8),
                            "type": "Project" if str(item.get("type", "")).lower().startswith("project") else "Homework",
                            "title": title[:140],
                            "subject": str(item.get("subject", "")).strip() or "General",
                            "due_date": due.isoformat(),
                            "estimated_hours": max(0.5, min(100.0, float(item.get("estimated_hours", 1.0) or 1.0))),
                            "done": False,
                        })
                current = db.get_master_timetable(user["username"]) or {}
                db.save_master_timetable(user["username"], {
                    "imported_exams": clean_exams,
                    "imported_assignments": clean_assignments,
                })
                st.success(f"Read {len(clean_exams)} exam record(s) and {len(clean_assignments)} project/homework item(s). Please check the imported details below.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not read this upload. Try a clearer image/PDF or enter the details manually. ({str(exc)[:180]})")

    saved = db.get_master_timetable(user["username"]) or {}
    imported_exams = saved.get("imported_exams", [])
    imported_assignments = saved.get("imported_assignments", [])
    if imported_exams:
        with st.expander("Review imported exams"):
            for exam in imported_exams:
                st.write(f"**{exam['subject']}** — {exam['exam_date']} · {', '.join(exam.get('chapters', []))}")
    if imported_assignments:
        with st.expander("Review imported projects / homework"):
            for item in imported_assignments:
                st.write(f"**{item['type']}: {item['title']}** — {item['subject']} · due {item['due_date']} · {item['estimated_hours']:g} h")

    # Preview every deadline item before generation so missing selection or saved data is visible.
    preview_assignments = []
    for pod in selected_pods:
        preview_assignments.extend({**item, "_source": f"StudyPod: {pod.get('name', 'Unnamed')}"} for item in pod.get("projects", []) + pod.get("homeworks", []))
    preview_assignments.extend({**item, "_source": "Master timetable"} for item in saved.get("extra_assignments", []))
    preview_assignments.extend({**item, "_source": "Uploaded routine"} for item in imported_assignments)
    st.markdown("### Projects and homework included")
    if preview_assignments:
        for item in preview_assignments:
            st.write(f"• **{item.get('type', 'Homework')}: {item.get('title', 'Untitled')}** — {item.get('subject', 'General')} · due {item.get('due_date', 'date missing')} · {float(item.get('estimated_hours', 1) or 1):g} h · {item.get('_source', '')}")
    else:
        st.warning("No project or homework is currently saved for the selected StudyPods. Add it above or open Create a pod and save it there. Only tasks from selected StudyPods are included.")

    st.info("The timetable is generated in stages: chapter learning and practice first, then spaced revision and final revision. Weak subjects receive extra practice. Projects and homework are scheduled before their submission dates. You will see the next 7 days first.")

    if st.button("✨ Generate / update my master timetable", type="primary", use_container_width=True):
        if weekly_hours <= 0:
            st.error("Please enter some available study time.")
            return

        today = date.today()
        exam_records = []
        for pod in selected_pods:
            try:
                exam_day = date.fromisoformat(pod["exam_date"])
            except (ValueError, TypeError):
                continue
            exam_records.append({
                "subject": pod["subject"], "exam_date": exam_day.isoformat(),
                "chapters": list(pod.get("chapters", [])),
                "weak": pod["subject"] in weak_subjects,
            })
        for exam in imported_exams:
            exam_records.append({
                "subject": exam["subject"], "exam_date": exam["exam_date"],
                "chapters": exam.get("chapters", []),
                "weak": exam["subject"] in weak_subjects,
            })

        # Merge duplicate subject/exam entries and retain their chapter list.
        merged = {}
        for exam in exam_records:
            key = (exam["subject"].casefold(), exam["exam_date"])
            if key not in merged:
                merged[key] = dict(exam)
            else:
                merged[key]["chapters"] = list(dict.fromkeys(merged[key]["chapters"] + exam["chapters"]))
        exam_records = list(merged.values())
        if not exam_records and not imported_assignments:
            st.error("No future exams or imported assignments were found. Add a StudyPod or upload your routine.")
            return

        assignments = []
        for pod in selected_pods:
            for item in pod.get("projects", []) + pod.get("homeworks", []):
                assignments.append({**item, "id": item.get("id", secrets.token_hex(8)), "done": bool(item.get("done", False))})
        assignments += list(saved.get("extra_assignments", []))
        assignments += list(imported_assignments)

        # Show a transparent audit of every deadline item included in this plan.
        if assignments:
            with st.expander(f"🔎 Deadline items detected ({len(assignments)})", expanded=True):
                for item in assignments:
                    st.write(
                        f"**{item.get('type', 'Homework')}: {item.get('title', 'Untitled')}**"
                        f" · {item.get('subject', 'General')} · due {item.get('due_date', 'date missing')}"
                        f" · {float(item.get('estimated_hours', 1) or 1):g} h"
                    )
        else:
            st.warning("No projects or homework were found in the selected StudyPods or Master timetable. Check that you selected the correct StudyPod and saved the task.")

        all_dates = [date.fromisoformat(x["exam_date"]) for x in exam_records]
        all_dates += [date.fromisoformat(x["due_date"]) for x in assignments]
        end_date = max(all_dates) if all_dates else today + timedelta(days=30)
        end_date = max(today, end_date)
        total_days = min((end_date - today).days + 1, 365)
        if (end_date - today).days + 1 > 365:
            st.warning("The timetable is limited to the next 365 days.")

        rows = [{
            "date": (today + timedelta(days=i)).isoformat(),
            "day": (today + timedelta(days=i)).strftime("%A"),
            "capacity": float(hours[(today + timedelta(days=i)).strftime("%A").lower()]),
            "tasks": [],
        } for i in range(total_days)]

        task_queue = []
        for exam in exam_records:
            exam_day = date.fromisoformat(exam["exam_date"])
            if exam_day < today:
                continue
            chapters = exam.get("chapters", [])
            for chapter in chapters:
                milestones = [
                    (max(today, exam_day - timedelta(days=21)), "Learn and understand", 1.0),
                    (max(today, exam_day - timedelta(days=14)), "Solve questions / practise", 1.0),
                    (max(today, exam_day - timedelta(days=7)), "Revision 1 — active recall", 0.5),
                    (max(today, exam_day - timedelta(days=2)), "Final revision — timed questions", 0.5),
                ]
                if exam.get("weak"):
                    milestones.append((max(today, exam_day - timedelta(days=10)), "Extra weak-subject practice", 1.0))
                for target, phase, duration in milestones:
                    task_queue.append({
                        "id": secrets.token_hex(8), "kind": "Exam",
                        "subject": exam["subject"], "chapter": chapter,
                        "title": chapter, "phase": phase,
                        "hours": duration, "target_date": target.isoformat(),
                        "due_date": exam_day.isoformat(), "done": False,
                    })

        for item in assignments:
            try:
                due = date.fromisoformat(item["due_date"])
            except (ValueError, TypeError):
                continue
            if due < today:
                continue
            remaining = max(0.5, float(item.get("estimated_hours", 1.0) or 1.0))
            while remaining > 0:
                chunk = min(1.0, remaining)
                task_queue.append({
                    "id": item.get("id", secrets.token_hex(8)), "kind": item.get("type", "Homework"),
                    "subject": item.get("subject", "General"), "chapter": "",
                    "title": item["title"], "phase": "Complete and submit",
                    "hours": chunk, "target_date": due.isoformat(),
                    "due_date": due.isoformat(), "done": bool(item.get("done", False)),
                })
                remaining = round(remaining - chunk, 2)

        task_queue.sort(key=lambda t: (t["target_date"], 0 if t["kind"] in ("Project", "Homework") else 1, t["subject"], t["title"]))
        # Spread each session across the least-loaded eligible day on or before
        # its target. This uses the available time throughout the calendar rather
        # than leaving early days empty and packing everything near deadlines.
        pending = []
        for task in task_queue:
            placed = False
            latest_date = min(task.get("target_date", task.get("due_date", end_date.isoformat())),
                              task.get("due_date", end_date.isoformat()))
            eligible = []
            for row in rows:
                if row["date"] > latest_date or float(row["capacity"]) <= 0:
                    continue
                used = sum(float(t.get("hours", 0) or 0) for t in row["tasks"])
                spare = round(float(row["capacity"]) - used, 2)
                if float(task["hours"]) <= spare:
                    load_ratio = used / float(row["capacity"])
                    eligible.append((load_ratio, row["date"], row))
            for _, _, row in sorted(eligible, key=lambda item: (item[0], item[1])):
                row["tasks"].append(task)
                placed = True
                break
            if not placed:
                pending.append(task)
        # Add a steady daily study routine after deadline work and exam milestones
        # have been placed. Use up to 85% of each day's capacity, keeping a buffer
        # for breaks, meals and unexpected school work.
        study_pool = [
            exam for exam in exam_records
            if exam.get("chapters") and date.fromisoformat(exam["exam_date"]) >= today
        ]
        study_pool.sort(key=lambda item: (item["exam_date"], item["subject"]))
        if study_pool:
            for day_index, row in enumerate(rows):
                capacity = float(row["capacity"])
                target_hours = round(capacity * 0.85, 2)
                used_hours = sum(float(task.get("hours", 0) or 0) for task in row["tasks"])
                slot_index = 0
                while used_hours + 0.49 < target_hours:
                    spare_to_target = round(target_hours - used_hours, 2)
                    duration = min(1.0, spare_to_target)
                    if duration < 0.5:
                        break
                    exam = study_pool[(day_index + slot_index) % len(study_pool)]
                    chapters = exam.get("chapters", [])
                    chapter = chapters[((day_index // max(1, len(study_pool))) + slot_index) % len(chapters)]
                    row["tasks"].append({
                        "id": secrets.token_hex(8),
                        "kind": "Daily study",
                        "subject": exam["subject"],
                        "chapter": chapter,
                        "title": chapter,
                        "phase": "Understand, practise and review",
                        "hours": duration,
                        "target_date": row["date"],
                        "due_date": exam["exam_date"],
                        "done": False,
                    })
                    used_hours = round(used_hours + duration, 2)
                    slot_index += 1

        for row in rows:
            row["tasks"].sort(key=lambda task: (task.get("kind", "") not in ("Project", "Homework"), task.get("subject", ""), task.get("title", "")))

        db.save_master_timetable(user["username"], {
            "pod_ids": selected_ids,
            "hours": hours,
            "weak_subjects": weak_subjects,
            "schedule": rows,
            "last_exam": end_date.isoformat(),
            "pending_sessions": pending,
            "generated_at": db.utcnow(),
        })
        if pending:
            st.warning(f"Timetable saved, but {len(pending)} sessions could not fit before their deadlines. Increase available time or reduce the workload where possible.")
        else:
            st.success("Your combined timetable is ready, including revision, projects and homework.")
        st.rerun()

    saved = db.get_master_timetable(user["username"]) or {}
    schedule = saved.get("schedule", [])
    if not schedule:
        st.info("Enter your daily hours and generate your first timetable.")
        return

    st.markdown("---")
    st.markdown("### My timetable")
    view_mode = st.radio(
        "How much of the timetable would you like to see?",
        ["Coming 7 days", "Coming 14 days", "Coming 30 days", "Choose number of days", "Whole timetable"],
        horizontal=True,
        key="master_view_mode",
    )
    if view_mode == "Coming 7 days":
        view_count = 7
    elif view_mode == "Coming 14 days":
        view_count = 14
    elif view_mode == "Coming 30 days":
        view_count = 30
    elif view_mode == "Choose number of days":
        view_count = st.number_input("Number of days to display", min_value=1, max_value=365, value=14, step=1)
    else:
        view_count = len(schedule)

    st.caption("Tick tasks as completed. If you miss work, use the rearrange button below to rebuild the remaining timetable.")
    today_text = date.today().isoformat()
    upcoming_schedule = [day for day in schedule if day.get("date", "") >= today_text]
    for day in upcoming_schedule[:int(view_count)]:
        with st.container(border=True):
            st.markdown(f"**{day['day']} · {day['date']}**")
            planned = sum(float(t.get("hours", 0) or 0) for t in day.get("tasks", []))
            st.caption(f"Planned: {planned:g} / {float(day.get('capacity', 0) or 0):g} hours")
            if not day.get("tasks"):
                st.write("Rest / no tasks scheduled.")
            for task_index, task in enumerate(day.get("tasks", [])):
                label = f"{task.get('kind', 'Study')} · {task.get('subject', '')} · {task.get('title', task.get('chapter', 'Task'))} — {task.get('phase', '')} ({task.get('hours', 0):g} h)"
                task["done"] = st.checkbox(
                    label, value=bool(task.get("done", False)),
                    key=f"master_done_{day['date']}_{task.get('id', task_index)}_{task_index}",
                )
    col_a, col_b = st.columns([1, 2])
    with col_a:
        if st.button("Save progress", key="save_master_progress"):
            db.save_master_timetable(user["username"], {
                "pod_ids": saved.get("pod_ids", []), "hours": saved.get("hours", {}),
                "weak_subjects": saved.get("weak_subjects", []), "schedule": schedule,
                "last_exam": saved.get("last_exam", ""),
                "pending_sessions": saved.get("pending_sessions", []),
                "extra_assignments": saved.get("extra_assignments", []),
                "imported_exams": saved.get("imported_exams", []),
                "imported_assignments": saved.get("imported_assignments", []),
            })
            st.success("Progress saved.")
            st.rerun()
    with col_b:
        if st.button("🔄 Rearrange missed / unfinished tasks", key="rebuild_master_schedule"):
            unfinished = []
            completed_past = []
            for day in schedule:
                for task in day.get("tasks", []):
                    if task.get("done"):
                        if day["date"] >= today_text:
                            completed_past.append((day["date"], dict(task)))
                    else:
                        pending_task = dict(task)
                        old_target = pending_task.get("target_date", pending_task.get("due_date", today_text))
                        pending_task["target_date"] = max(today_text, old_target)
                        unfinished.append(pending_task)
            remaining_rows = [{
                "date": (date.today() + timedelta(days=i)).isoformat(),
                "day": (date.today() + timedelta(days=i)).strftime("%A"),
                "capacity": float(saved.get("hours", {}).get((date.today() + timedelta(days=i)).strftime("%A").lower(), 0)),
                "tasks": [],
            } for i in range(min(365, max(1, (date.fromisoformat(saved.get("last_exam", today_text)) - date.today()).days + 1)))]
            for old_date, task in completed_past:
                row = next((x for x in remaining_rows if x["date"] == old_date), None)
                if row:
                    row["tasks"].append(task)
            pending = []
            for task in sorted(unfinished, key=lambda t: (t.get("target_date", t.get("due_date", "9999-12-31")), 0 if t.get("kind") in ("Project", "Homework") else 1)):
                placed = False
                latest_date = min(task.get("target_date", task.get("due_date", "9999-12-31")), task.get("due_date", "9999-12-31"))
                eligible = []
                for row in remaining_rows:
                    if row["date"] > latest_date or float(row["capacity"]) <= 0:
                        continue
                    used = sum(float(t.get("hours", 0) or 0) for t in row["tasks"])
                    spare = round(float(row["capacity"]) - used, 2)
                    if float(task.get("hours", 0) or 0) <= spare:
                        eligible.append((used / float(row["capacity"]), row["date"], row))
                for _, _, row in sorted(eligible, key=lambda item: (item[0], item[1])):
                    row["tasks"].append(task)
                    placed = True
                    break
                if not placed:
                    pending.append(task)
            db.save_master_timetable(user["username"], {
                "pod_ids": saved.get("pod_ids", []), "hours": saved.get("hours", {}),
                "weak_subjects": saved.get("weak_subjects", []), "schedule": remaining_rows,
                "last_exam": saved.get("last_exam", ""),
                "pending_sessions": pending,
                "extra_assignments": saved.get("extra_assignments", []),
                "imported_exams": saved.get("imported_exams", []),
                "imported_assignments": saved.get("imported_assignments", []),
            })
            if pending:
                st.warning(f"Rearranged what could fit. {len(pending)} task session(s) still cannot fit before their deadlines.")
            else:
                st.success("Your remaining timetable has been rearranged.")
            st.rerun()

    if saved.get("pending_sessions"):
        st.warning(f"{len(saved['pending_sessions'])} sessions are not currently scheduled because the available hours before deadlines are insufficient.")

def main():
    st.markdown('<div class="hero"><h1>📚 StudyPod</h1><p>Small groups. Smart sprints. Shared accountability.</p></div>', unsafe_allow_html=True)
    if not require_login():
        return
    user = st.session_state.user
    with st.sidebar:
        st.markdown("### StudyPod")
        st.write(f"Signed in as **{user['display_name']}**")
        if st.button("Log out", use_container_width=True):
            st.session_state.pop("user", None)
            st.session_state.pop("active_pod_id", None)
            st.rerun()
        st.markdown("---")
        st.caption("Built & Owned by NilanjanC")

    try:
        db.get_db().command("ping")
    except Exception as exc:
        st.error(f"Cannot connect to MongoDB. Check Streamlit Secrets and Atlas Network Access. Details: {exc}")
        return

    create_tab, join_tab, pods_tab, master_tab = st.tabs(["➕ Create a pod", "🔑 Join with code", "📚 My StudyPods", "🗓️ Master timetable"])
    with create_tab:
        create_pod_ui(user)
    with join_tab:
        join_pod_ui(user)
    with master_tab:
        master_timetable_ui(user)
    with pods_tab:
        pods = db.get_user_pods(user["username"])
        if not pods:
            st.info("You haven't joined a StudyPod yet. Create one or join with an invite code.")
        for pod in pods:
            is_owner = pod.get("owner_username") == user["username"]
            columns = st.columns([4, 1, 1] if is_owner else [4, 1])
            with columns[0]:
                st.markdown(f"**{pod['name']}**")
                st.caption(f"{pod['class_name']} · {pod['board']} · {pod['subject']} · Exam {pod['exam_date']}")
            with columns[1]:
                if st.button("Open", key=f"open_pod_{pod['_id']}"):
                    st.session_state.active_pod_id = str(pod["_id"])
                    st.rerun()
            if is_owner:
                with columns[2]:
                    if st.button("Delete", key=f"request_delete_pod_{pod['_id']}", type="secondary"):
                        st.session_state.delete_pod_id = str(pod["_id"])
                        st.rerun()

        pending_delete = st.session_state.get("delete_pod_id")
        if pending_delete:
            target = next((p for p in pods if str(p["_id"]) == pending_delete), None)
            if target and target.get("owner_username") == user["username"]:
                st.warning(f"Delete **{target['name']}** permanently? Its members, weekly milestones, proof submissions and confidence ratings will also be deleted.")
                confirm_col, cancel_col = st.columns(2)
                with confirm_col:
                    if st.button("Yes, permanently delete this StudyPod", key="confirm_delete_pod", type="primary"):
                        if db.delete_pod(ObjectId(pending_delete), user["username"]):
                            st.session_state.pop("delete_pod_id", None)
                            if st.session_state.get("active_pod_id") == pending_delete:
                                st.session_state.pop("active_pod_id", None)
                            st.success("StudyPod and its associated records were deleted.")
                            st.rerun()
                        else:
                            st.error("The StudyPod could not be deleted. Only its owner can delete it.")
                with cancel_col:
                    if st.button("Cancel deletion", key="cancel_delete_pod"):
                        st.session_state.pop("delete_pod_id", None)
                        st.rerun()

    active_pod = st.session_state.get("active_pod_id")
    if active_pod:
        st.markdown("---")
        if st.button("← Back to my pods", key="back_to_pods"):
            st.session_state.pop("active_pod_id", None)
            st.rerun()
        open_pod_ui(user, active_pod)

    show_donation()
    st.markdown("---")
    st.markdown('<p class="owner">Built &amp; Owned by NilanjanC · StudyPod MVP</p>', unsafe_allow_html=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        st.error("StudyPod encountered an unexpected error.")
        st.exception(exc)
