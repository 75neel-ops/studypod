from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class DayPlan(BaseModel):
    date: str
    day: str
    available_hours: float = Field(ge=0, le=12)
    planned_hours: float = Field(ge=0, le=12)
    focus: str


class WeekPlan(BaseModel):
    week_number: int
    start_date: str
    end_date: str
    title: str
    topics: list[str]
    tasks: list[str]
    daily_schedule: list[DayPlan]


class StudyPlan(BaseModel):
    weeks: list[WeekPlan]


def _week_dates(exam_date: date):
    today = date.today()
    if exam_date < today:
        raise ValueError("Exam date must be today or in the future.")
    result = []
    cursor = today
    week = 1
    while cursor <= exam_date and week <= 26:
        end = min(exam_date, cursor + timedelta(days=6))
        result.append((week, cursor, end))
        cursor = end + timedelta(days=1)
        week += 1
    return result


def deterministic_plan(chapters: list[str], exam_date: date, daily_hours: dict[str, float]) -> StudyPlan:
    spans = _week_dates(exam_date)
    weeks: list[WeekPlan] = []
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for week_no, start, end in spans:
        first = ((week_no - 1) * len(chapters)) // len(spans)
        last = (week_no * len(chapters)) // len(spans)
        topics = chapters[first:last] or [chapters[min(week_no - 1, len(chapters) - 1)]]
        days = []
        cursor = start
        while cursor <= end:
            day = day_names[cursor.weekday()]
            available = float(daily_hours.get(day.lower(), 0))
            planned = round(available * 0.85, 2)
            topic = topics[(cursor - start).days % len(topics)]
            days.append(DayPlan(
                date=cursor.isoformat(),
                day=day,
                available_hours=available,
                planned_hours=planned,
                focus=(f"{topic}: concepts, active recall and board-style practice" if planned else "Rest / school and tuition commitments"),
            ))
            cursor += timedelta(days=1)
        weeks.append(WeekPlan(
            week_number=week_no,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            title=f"Week {week_no}: {', '.join(topics[:2])}",
            topics=topics,
            tasks=[
                "Learn concepts and make concise notes",
                "Solve textbook and board-style questions",
                "Review mistakes and take a short self-test",
            ],
            daily_schedule=days,
        ))
    return StudyPlan(weeks=weeks)


def _normalise_plan(plan: StudyPlan, chapters: list[str], exam_date: date,
                    daily_hours: dict[str, float]) -> StudyPlan:
    # Enforce date coverage and declared daily capacity even if the model returns an imperfect plan.
    fallback = deterministic_plan(chapters, exam_date, daily_hours)
    by_date = {}
    for week in plan.weeks:
        for day in week.daily_schedule:
            by_date[day.date] = day
    clean_weeks = []
    for base_week in fallback.weeks:
        clean_days = []
        for base_day in base_week.daily_schedule:
            candidate = by_date.get(base_day.date)
            if candidate:
                cap = float(daily_hours.get(base_day.day.lower(), 0))
                planned = min(max(0.0, float(candidate.planned_hours)), cap)
                clean_days.append(DayPlan(
                    date=base_day.date,
                    day=base_day.day,
                    available_hours=cap,
                    planned_hours=round(planned, 2),
                    focus=(candidate.focus or base_day.focus)[:220],
                ))
            else:
                clean_days.append(base_day)
        clean_weeks.append(WeekPlan(
            week_number=base_week.week_number,
            start_date=base_week.start_date,
            end_date=base_week.end_date,
            title=(plan.weeks[base_week.week_number - 1].title
                   if base_week.week_number <= len(plan.weeks) else base_week.title)[:120],
            topics=(plan.weeks[base_week.week_number - 1].topics
                    if base_week.week_number <= len(plan.weeks) else base_week.topics) or base_week.topics,
            tasks=(plan.weeks[base_week.week_number - 1].tasks
                   if base_week.week_number <= len(plan.weeks) else base_week.tasks) or base_week.tasks,
            daily_schedule=clean_days,
        ))
    return StudyPlan(weeks=clean_weeks)


def generate_sprint(chapters: list[str], exam_date: date, daily_hours: dict[str, float],
                    class_name: str, board: str, subject: str, total_marks: int) -> tuple[StudyPlan, str]:
    fallback = deterministic_plan(chapters, exam_date, daily_hours)
    try:
        import streamlit as st
        from google import genai
        from google.genai import types

        api_key = st.secrets.get("gemini", {}).get("api_key", "")
        if not api_key:
            return fallback, "Deterministic planner (Gemini key not configured)"
        model = st.secrets.get("gemini", {}).get("model", "gemini-3.5-flash-lite")
        client = genai.Client(api_key=api_key)
        prompt = f"""
Create a realistic board-exam weekly and daily study sprint.
Class: {class_name}; Board: {board}; Subject: {subject}; Total marks: {total_marks}.
Exam date: {exam_date.isoformat()}.
Selected chapters (use only these): {json.dumps(chapters, ensure_ascii=False)}.
Maximum available study hours by weekday: {json.dumps(daily_hours)}.
Return one week per calendar block starting today and ending on exam date.
Every day must appear. Never exceed the stated available hours. Zero-hour days must have 0 planned hours.
Plan no more than 85% of each day's capacity, leaving room for breaks and homework.
Include concept learning, active recall, textbook questions, timed board-style practice, revision and error review.
Do not claim official chapter-wise mark weightages unless supplied. Use estimated study emphasis only.
Dates must be YYYY-MM-DD. Keep daily focus concise and actionable.
"""
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=StudyPlan,
                temperature=0.2,
            ),
        )
        parsed = StudyPlan.model_validate_json(response.text or "{}")
        return _normalise_plan(parsed, chapters, exam_date, daily_hours), f"Gemini: {model}"
    except Exception as exc:
        return fallback, f"Deterministic fallback (Gemini unavailable: {str(exc)[:140]})"


def suggest_chapters(class_name: str, board: str, subject: str) -> list[str]:
    try:
        import streamlit as st
        from google import genai
        from google.genai import types
        api_key = st.secrets.get("gemini", {}).get("api_key", "")
        if not api_key:
            return []
        model = st.secrets.get("gemini", {}).get("model", "gemini-3.5-flash-lite")
        client = genai.Client(api_key=api_key)
        class ChapterList(BaseModel):
            chapters: list[str]
        prompt = (
            f"Suggest a concise list of likely syllabus chapter/topic names for {class_name}, "
            f"{board}, subject {subject}, India. Return only chapter names. "
            "If the exact board syllabus is uncertain, say so in a short note field and do not invent certainty."
            )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ChapterList,
                temperature=0.1,
            ),
        )
        result = ChapterList.model_validate_json(response.text or "{}")
        return list(dict.fromkeys(x.strip() for x in result.chapters if x.strip()))[:30]
    except Exception:
        return []
