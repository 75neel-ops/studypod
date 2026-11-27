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
    st.caption("Build a sprint around your exam date and the hours you can realistically study after school and tuition.")
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
        st.markdown("**Your available study time**")
        st.caption("Enter your realistic maximum hours after school, tuition and other commitments. Enter 0 on days you cannot study.")
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        defaults = [1.5, 1.5, 1.5, 1.5, 1.5, 3.0, 3.0]
        daily_hours = {}
        cols = st.columns(4)
        for idx, day in enumerate(day_names):
            with cols[idx % 4]:
                daily_hours[day.lower()] = st.number_input(
                    day, min_value=0.0, max_value=12.0, value=defaults[idx],
                    step=0.5, key=f"hours_{day.lower()}",
                )
        weekly_available_hours = sum(daily_hours.values())
        if weekly_available_hours < 7:
            st.warning(
                f"You have entered only {weekly_available_hours:g} study hours for the whole week. "
                "That is likely too little for steady exam preparation. Increase the hours on some days "
                "if possible, without sacrificing sleep or essential commitments."
            )
        elif weekly_available_hours < 10.5:
            st.info(
                f"You have entered {weekly_available_hours:g} hours per week. "
                "StudyPod recommends aiming for around 10.5 hours weekly (about 1.5 hours daily on average), "
                "if your routine allows."
            )
        syllabus_file = st.file_uploader("Syllabus / routine PDF or image (optional)", type=["pdf", "png", "jpg", "jpeg", "webp"], key="syllabus_upload")
        submitted = st.form_submit_button("Create my StudyPod and sprint", type="primary", use_container_width=True)

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
        if not any(daily_hours.values()):
            st.error("Please make at least one study hour available during the week.")
            return
        with st.spinner("Building a sprint that respects your daily availability..."):
            plan, source = generate_sprint(chapters, exam_date, daily_hours, class_name, board, subject, total_marks)
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
                "daily_hours": daily_hours,
                "syllabus_file_id": syllabus_id,
                "invite_code": make_invite_code(),
                "created_at": db.utcnow(),
                "planner_source": source,
            }
            pod_id = ObjectId(db.create_pod_document(pod_doc))
            db.add_member(pod_id, user["username"], user["display_name"], "owner")
            db.create_milestones(pod_id, [week.model_dump() for week in plan.weeks])
        st.success(f"StudyPod created! Invite code: {pod_doc['invite_code']}")
        st.info(f"Sprint source: {source}. Share the invite code with up to four other students.")
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
        st.write("**Your available hours:** " + " · ".join(f"{d.title()}: {h:g}h" for d, h in pod.get("daily_hours", {}).items()))
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
    tabs = st.tabs(["1 · Daily sprint", "2 · Proof of work", "3 · Group vault", "4 · Confidence & agenda"])

    with tabs[0]:
        st.markdown(f"### {milestone.get('title', 'Weekly sprint')}")
        st.write("Topics: " + ", ".join(milestone.get("topics", [])))
        st.write("**Weekly tasks**")
        for task in milestone.get("tasks", []):
            st.write("• " + task)
        # Build a private schedule for this learner so one student's missed work
        # never changes another pod member's timetable.
        learner_plan = db.get_learner_plan(pod_id, user["username"])
        if not learner_plan:
            base_schedule = []
            for week in milestones:
                for item in week.get("daily_schedule", []):
                    day_item = dict(item)
                    day_item["base_planned_hours"] = float(day_item.get("planned_hours", 0) or 0)
                    day_item["base_focus"] = str(day_item.get("focus", ""))
                    base_schedule.append(day_item)
            base_schedule.sort(key=lambda item: item.get("date", ""))
            db.save_learner_plan(pod_id, user["username"], base_schedule)
            learner_plan = db.get_learner_plan(pod_id, user["username"])
        learner_schedule = learner_plan.get("schedule", []) if learner_plan else []
        # Backfill the base values for plans created before task tracking was introduced.
        for item in learner_schedule:
            item.setdefault("base_planned_hours", float(item.get("planned_hours", 0) or 0))
            item.setdefault("base_focus", str(item.get("focus", "")))
        db.save_learner_plan(pod_id, user["username"], learner_schedule)

        progress_records = db.get_task_progress(pod_id, user["username"])
        progress_by_date = {item["date"]: item for item in progress_records}
        weekly_hours = sum(float(value or 0) for value in pod.get("daily_hours", {}).values())
        if weekly_hours < 7:
            st.error(
                f"Your available study time is only {weekly_hours:g} hours per week. "
                "This is very low for exam preparation. Please increase your study time where possible; "
                "aim for at least 1–1.5 hours on most days, while protecting sleep and school commitments."
            )
        elif weekly_hours < 10.5:
            st.warning(
                f"You have {weekly_hours:g} study hours per week. Consider adding another 2–3 hours weekly "
                "if your school, tuition and rest schedule allows."
            )

        st.markdown("**Your daily schedule and task completion**")
        st.caption("After each study day, record whether you completed the task and how much time you actually studied. StudyPod will adjust the remaining plan when work is missed.")
        learner_days = {item.get("date"): item for item in learner_schedule}
        for day in milestone.get("daily_schedule", []):
            current_day = learner_days.get(day["date"], day)
            saved = progress_by_date.get(day["date"], {})
            with st.container(border=True):
                st.markdown(f"**{day['day']} · {day['date']}**")
                st.write(f"**Planned: {float(current_day.get('planned_hours', 0) or 0):g} / {float(current_day.get('available_hours', 0) or 0):g} hours**")
                st.caption(current_day.get("focus", day.get("focus", "")))
                with st.form(f"daily_task_{milestone_id}_{day['date']}"):
                    status_options = ["Not started", "Completed", "Partly completed"]
                    current_status = saved.get("status", "Not started")
                    status_index = status_options.index(current_status) if current_status in status_options else 0
                    task_status = st.selectbox(
                        "Did you complete today's study task?",
                        status_options,
                        index=status_index,
                        key=f"task_status_{milestone_id}_{day['date']}",
                    )
                    hours_spent = st.number_input(
                        "Actual study time (hours)",
                        min_value=0.0,
                        max_value=12.0,
                        value=float(saved.get("hours_spent", 0) or 0),
                        step=0.25,
                        key=f"task_hours_{milestone_id}_{day['date']}",
                    )
                    task_note = st.text_input(
                        "What was completed / what is still difficult? (optional)",
                        value=saved.get("note", ""),
                        key=f"task_note_{milestone_id}_{day['date']}",
                    )
                    task_saved = st.form_submit_button("Save completion status")
                if task_saved:
                    db.save_task_progress(
                        pod_id, user["username"], day["date"],
                        task_status, hours_spent, task_note,
                    )
                    refreshed_progress = db.get_task_progress(pod_id, user["username"])
                    refreshed_by_date = {item["date"]: item for item in refreshed_progress}
                    today_text = date.today().isoformat()
                    backlog = 0.0
                    for planned_day in learner_schedule:
                        planned_date = str(planned_day.get("date", ""))
                        if planned_date <= today_text and planned_date in refreshed_by_date:
                            record = refreshed_by_date[planned_date]
                            if record.get("status") != "Completed":
                                base_hours = float(planned_day.get("base_planned_hours", planned_day.get("planned_hours", 0)) or 0)
                                spent = float(record.get("hours_spent", 0) or 0)
                                backlog += max(0.0, base_hours - spent)
                    # Always start from the original plan before redistributing backlog,
                    # preventing the same missed hours from being added repeatedly.
                    reset_schedule = []
                    for planned_day in learner_schedule:
                        copy_day = dict(planned_day)
                        if str(copy_day.get("date", "")) > today_text:
                            copy_day["planned_hours"] = float(copy_day.get("base_planned_hours", copy_day.get("planned_hours", 0)) or 0)
                            copy_day["focus"] = str(copy_day.get("base_focus", copy_day.get("focus", "")))
                        reset_schedule.append(copy_day)
                    revised_schedule, unmet_hours = rebalance_schedule(reset_schedule, backlog, today_text)
                    db.save_learner_plan(pod_id, user["username"], revised_schedule)
                    if backlog > 0:
                        if unmet_hours > 0:
                            future_days = sum(
                                1 for item in revised_schedule
                                if str(item.get("date", "")) > today_text
                                and float(item.get("available_hours", 0) or 0) > 0
                            )
                            extra_per_day = unmet_hours / max(1, future_days)
                            st.session_state["task_feedback"] = (
                                f"Your plan has been adjusted, but {unmet_hours:.2f} hours cannot fit into your current availability. "
                                f"Please consider adding about {extra_per_day:.2f} extra study hours on each remaining study day, "
                                "if practical. If that is not possible, prioritise the most important topics and speak to your teacher."
                            )
                        else:
                            st.session_state["task_feedback"] = (
                                f"Your remaining plan has been adjusted to include {backlog:.2f} catch-up hours. "
                                "Future study sessions are slightly longer, within the availability you entered."
                            )
                    else:
                        st.session_state["task_feedback"] = "Progress saved. Your remaining schedule is up to date."
                    st.rerun()
        feedback = st.session_state.pop("task_feedback", None)
        if feedback:
            if "cannot fit" in feedback:
                st.warning(feedback)
            else:
                st.success(feedback)
        st.caption(pod.get("planner_source", "StudyPod sprint planner"))

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
    st.caption("One combined timetable for all selected subjects. Your daily hours are a TOTAL budget shared across subjects.")
    all_pods = db.get_user_pods(user["username"])
    if not all_pods:
        st.info("Create or join at least one subject StudyPod first.")
        return

    labels = {
        f"{p['name']} · {p['subject']} · Exam {p['exam_date']}": str(p["_id"])
        for p in all_pods
    }
    selected_labels = st.multiselect(
        "Choose the subjects / StudyPods to include",
        options=list(labels.keys()),
        default=list(labels.keys()),
        key="master_selected_pods",
        help="Select one subject or combine all five (or more) subjects.",
    )
    selected_ids = [labels[label] for label in selected_labels]
    selected_pods = [p for p in all_pods if str(p["_id"]) in selected_ids]
    if not selected_pods:
        st.warning("Select at least one subject StudyPod.")
        return

    st.markdown("**Your total study hours available each day**")
    st.caption("These are not per-subject hours. StudyPod will divide this single daily budget among the selected subjects. You can enter a different number for every weekday.")
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    defaults = [3.0, 3.0, 3.0, 3.0, 3.0, 5.0, 5.0]
    hours = {}
    cols = st.columns(4)
    for index, day in enumerate(day_names):
        with cols[index % 4]:
            hours[day.lower()] = st.number_input(
                day, min_value=0.0, max_value=16.0, value=defaults[index],
                step=0.5, key=f"master_hours_{day.lower()}",
            )
    total_weekly = sum(hours.values())
    st.metric("Total available study time per week", f"{total_weekly:g} hours")
    if total_weekly <= 0:
        st.warning("Enter at least some study time during the week.")
    elif total_weekly < 14:
        st.warning("Your weekly study time is limited for several subjects. The planner will still use your available time, but check whether the workload is realistic.")

    st.markdown("**Subjects and exam dates**")
    for pod in sorted(selected_pods, key=lambda item: item["exam_date"]):
        st.write(f"• **{pod['subject']}** — {len(pod.get('chapters', []))} chapters · Exam {pod['exam_date']}")

    st.info("The timetable uses three stages: learn and practise every selected chapter, then revise it, then do a final recall/test. It rotates subjects so you do not have to study every subject every day. Some days may focus on only one or two subjects.")

    if st.button("✨ Generate my intelligent combined timetable", type="primary", use_container_width=True):
        if total_weekly <= 0:
            st.error("Please enter at least some study time.")
            return

        today = date.today()
        valid_pods = []
        for pod in selected_pods:
            try:
                exam_day = date.fromisoformat(pod["exam_date"])
            except (ValueError, TypeError):
                continue
            if exam_day >= today and pod.get("chapters"):
                valid_pods.append((pod, exam_day))
        if not valid_pods:
            st.error("The selected StudyPods have no future exam dates or no selected chapters.")
            return

        last_exam = max(exam_day for _, exam_day in valid_pods)
        days_count = min((last_exam - today).days + 1, 365)
        if (last_exam - today).days + 1 > 365:
            st.warning("For now, the timetable is limited to the next 365 days.")
        if days_count <= 0:
            st.error("The selected exams are in the past. Update the exam dates in your StudyPods.")
            return

        # Build three distinct rounds rather than repeating the same chapter list:
        # core learning + practice, spaced revision, and final recall/test.
        chapter_items = []
        for pod, exam_day in valid_pods:
            for chapter in pod.get("chapters", []):
                chapter_items.append({
                    "pod_id": str(pod["_id"]),
                    "pod_name": pod["name"],
                    "subject": pod["subject"],
                    "chapter": str(chapter),
                    "exam_date": exam_day.isoformat(),
                })
        if not chapter_items:
            st.error("No chapters were found in the selected StudyPods.")
            return

        # Earlier exams receive priority, while subject rotation avoids long runs
        # of the same subject. Stable order makes regeneration predictable.
        chapter_items.sort(key=lambda x: (x["exam_date"], x["subject"], x["chapter"]))
        subject_order = []
        for item in chapter_items:
            if item["subject"] not in subject_order:
                subject_order.append(item["subject"])
        by_subject = {
            subject: [item for item in chapter_items if item["subject"] == subject]
            for subject in subject_order
        }

        # Each chapter receives two focused core sessions and two revision sessions.
        # Core work is placed in the first 60% of the available calendar;
        # revision 1 in the next 22%; final recall/test in the final 18%.
        total_days = days_count
        core_end = max(1, int(total_days * 0.60))
        revision_end = max(core_end + 1, int(total_days * 0.82))
        revision_end = min(total_days, revision_end)

        daily_rows = []
        for offset in range(total_days):
            current = today + timedelta(days=offset)
            capacity = float(hours.get(current.strftime("%A").lower(), 0))
            daily_rows.append({
                "date": current.isoformat(),
                "day": current.strftime("%A"),
                "capacity": capacity,
                "tasks": [],
            })

        def round_robin_items(items):
            grouped = {s: list(by_subject[s]) for s in subject_order}
            result = []
            while any(grouped.values()):
                for subject in subject_order:
                    if grouped[subject]:
                        result.append(grouped[subject].pop(0))
            return result

        ordered_chapters = round_robin_items(chapter_items)

        def place_sessions(items, start_idx, end_idx, phase, session_hours, description):
            # Spread sessions across the phase window and fill each day's available
            # time in half-hour blocks. No subject can consume more than the total cap.
            if end_idx <= start_idx:
                return 0
            session_queue = []
            for item in items:
                session_queue.append({**item, "phase": phase, "focus": description, "hours": session_hours, "done": False})
            if not session_queue:
                return 0
            cursor_idx = start_idx
            remaining = session_queue
            # One session per chapter per pass, rotating through subjects.
            while remaining and cursor_idx < end_idx:
                progressed = False
                for row_idx in range(cursor_idx, end_idx):
                    row = daily_rows[row_idx]
                    used = sum(float(t["hours"]) for t in row["tasks"])
                    spare = round(float(row["capacity"]) - used, 2)
                    if spare >= session_hours and remaining:
                        task = remaining.pop(0)
                        row["tasks"].append(task)
                        progressed = True
                if not remaining:
                    break
                if not progressed:
                    break
                cursor_idx = min(end_idx, cursor_idx + 1)
            return len(remaining)

        # Sessions are assigned in a controlled sequence. If the selected capacity
        # is insufficient, the app reports the remaining work rather than silently
        # dropping it or repeating chapters.
        core_items = []
        for item in ordered_chapters:
            core_items.extend([
                {**item, "session_label": "Learn / understand"},
                {**item, "session_label": "Solve questions / practise"},
            ])
        rev1_items = [{**item, "session_label": "Revision 1 — active recall"} for item in ordered_chapters]
        rev2_items = [{**item, "session_label": "Final revision — timed questions"} for item in ordered_chapters]

        # Allocate the core stage, then revision stages. Session sizes are 1 hour
        # for core work and 30 minutes for each revision round.
        core_queue = []
        for item in core_items:
            core_queue.append({**item, "phase": "Core", "focus": item["session_label"], "hours": 1.0, "done": False})
        rev1_queue = [
            {**item, "phase": "Revision 1", "focus": item["session_label"], "hours": 0.5, "done": False}
            for item in rev1_items
        ]
        rev2_queue = [
            {**item, "phase": "Final revision", "focus": item["session_label"], "hours": 0.5, "done": False}
            for item in rev2_items
        ]

        def allocate_queue(queue, first_day, last_day):
            pending = list(queue)
            for row_idx in range(first_day, min(last_day, len(daily_rows))):
                row = daily_rows[row_idx]
                used = sum(float(t["hours"]) for t in row["tasks"])
                spare = round(float(row["capacity"]) - used, 2)
                while pending and spare >= 0.5:
                    # Prefer a task that fits; preserve the queue's subject rotation.
                    fit_index = next((i for i, task in enumerate(pending) if float(task["hours"]) <= spare), None)
                    if fit_index is None:
                        break
                    task = pending.pop(fit_index)
                    row["tasks"].append(task)
                    spare = round(spare - float(task["hours"]), 2)
            return pending

        pending_core = allocate_queue(core_queue, 0, core_end)
        pending_rev1 = allocate_queue(rev1_queue, core_end, revision_end)
        pending_rev2 = allocate_queue(rev2_queue, revision_end, total_days)

        # Use any remaining free time for mixed-subject practice and exam preparation.
        # This is explicitly labelled as consolidation, not falsely assigned to a chapter.
        for row in daily_rows:
            used = sum(float(t["hours"]) for t in row["tasks"])
            spare = round(float(row["capacity"]) - used, 2)
            while spare >= 1.0:
                row["tasks"].append({
                    "pod_id": "", "pod_name": "All selected subjects",
                    "subject": "Mixed practice", "chapter": "Mixed-subject practice / mock test / error-log review",
                    "exam_date": last_exam.isoformat(), "phase": "Consolidation",
                    "focus": "Solve mixed questions, review mistakes, or take a timed mini-test",
                    "hours": 1.0, "done": False,
                })
                spare = round(spare - 1.0, 2)

        db.save_master_timetable(user["username"], {
            "pod_ids": [str(p["_id"]) for p, _ in valid_pods],
            "hours": hours,
            "schedule": daily_rows,
            "last_exam": last_exam.isoformat(),
            "pending_core_sessions": len(pending_core),
            "pending_revision1_sessions": len(pending_rev1),
            "pending_revision2_sessions": len(pending_rev2),
        })
        total_pending = len(pending_core) + len(pending_rev1) + len(pending_rev2)
        if total_pending:
            st.warning(f"Timetable saved, but {total_pending} chapter sessions could not fit into the selected date windows and daily hours. Review the workload or increase available time where practical.")
        else:
            st.success("Your combined timetable has been generated with chapter learning, practice and two revision rounds.")
        st.rerun()

    saved = db.get_master_timetable(user["username"])
    if saved and saved.get("schedule"):
        if set(saved.get("pod_ids", [])) != set(selected_ids) or saved.get("hours", {}) != hours:
            st.info("Your saved timetable uses different subjects or daily hours. Generate again to apply your current selections.")
        st.markdown("---")
        st.markdown("### Your day-wise study timetable")
        st.caption(f"Through {saved.get('last_exam', '')}. All subject sessions share the daily total-hour budget.")
        for day in saved["schedule"]:
            with st.container(border=True):
                st.markdown(f"**{day['day']} · {day['date']}**")
                st.caption(f"Planned: {sum(float(t.get('hours', 0) or 0) for t in day.get('tasks', [])):g} / {float(day.get('capacity', 0) or 0):g} hours")
                if not day.get("tasks"):
                    st.write("Rest / no study time entered.")
                for task_index, task in enumerate(day.get("tasks", [])):
                    title = f"{task['subject']} — {task['chapter']} · {task.get('focus', task.get('phase', 'Study'))} ({task['hours']:g} h)"
                    done = st.checkbox(
                        title,
                        value=bool(task.get("done", False)),
                        key=f"master_done_{day['date']}_{task_index}",
                    )
                    task["done"] = done
                if st.button("Save this day's progress", key=f"save_master_{day['date']}"):
                    db.save_master_timetable(user["username"], {
                        "pod_ids": saved.get("pod_ids", []),
                        "hours": saved.get("hours", {}),
                        "schedule": saved["schedule"],
                        "last_exam": saved.get("last_exam", ""),
                        "pending_core_sessions": saved.get("pending_core_sessions", 0),
                        "pending_revision1_sessions": saved.get("pending_revision1_sessions", 0),
                        "pending_revision2_sessions": saved.get("pending_revision2_sessions", 0),
                    })
                    st.success("Daily progress saved.")
                    st.rerun()
        pending = (
            int(saved.get("pending_core_sessions", 0))
            + int(saved.get("pending_revision1_sessions", 0))
            + int(saved.get("pending_revision2_sessions", 0))
        )
        if pending:
            st.warning(f"{pending} chapter sessions remain unallocated because the current date windows and available hours were not enough. Consider adding study hours or adjusting the exam plan.")

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
