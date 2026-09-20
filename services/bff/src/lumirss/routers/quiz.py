"""F069 quiz 路由 — 评分（只读答案表；无 AI/无配额）。

- POST /api/v1/quiz/{quiz_id}/grade：逐题判定 chosen vs answerIndex，
  返回 answerIndex/explanation/evidenceQuote（生成时已核验存在）。
- 会话不存在/已过期清理 → 404；answers 短于题数按未答（null）处理。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.ai_quiz import QuizSessionStore, answers_of
from lumirss.routers.entry_ai import QuizGradeBody, QuizGradeItem, QuizGradeResult

router = APIRouter()


@router.post("/api/v1/quiz/{quiz_id}/grade", response_model=QuizGradeResult)
async def grade_quiz(quiz_id: str, payload: QuizGradeBody, request: Request) -> Any:
    store = QuizSessionStore(request.app.state.db)
    row = await store.get(quiz_id)
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "quiz_not_found", "message": "自测会话不存在或已过期。"}},
        )
    answers = payload.answers
    items = [
        QuizGradeItem(
            index=int(answer["index"]),
            chosen=(
                answers[position]
                if position < len(answers) and answers[position] is not None
                else None
            ),
            correct=(
                position < len(answers)
                and answers[position] is not None
                and int(answers[position]) == int(answer["answerIndex"])
            ),
            answerIndex=int(answer["answerIndex"]),
            explanation=str(answer["explanation"]),
            evidenceQuote=str(answer["evidenceQuote"]),
        )
        for position, answer in enumerate(answers_of(row))
    ]
    return QuizGradeResult(quizId=str(row["id"]), items=items)
