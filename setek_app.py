import streamlit as st
import pdfplumber
import google.generativeai as genai
import pandas as pd
import numpy as np
import requests
import io
from datetime import datetime
from duckduckgo_search import DDGS

# ==========================================
# 1. API 및 구글 시트 설정
# ==========================================
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.5-flash")
    embed_model = "models/text-embedding-004" 
    # Secrets에 신규 저장용 시트 URL을 추가해야 함 (필수 아님)
    GSHEET_SAVE_URL = st.secrets.get("GSHEET_SET_URL", "") 
except Exception as e:
    st.error(f"⚠️ 설정 오류: {e}")

if "db_texts" not in st.session_state: st.session_state.db_texts = []
if "db_embeddings" not in st.session_state: st.session_state.db_embeddings = []
if "current_result" not in st.session_state: st.session_state.current_result = ""

def get_byte_length(text):
    return len(text.encode('utf-8'))

# ==========================================
# 2. RAG & 웹 검색 함수 (V3와 동일)
# ==========================================
def find_similar_setek(query, top_k=2):
    if not st.session_state.db_texts: return ""
    query_emb = genai.embed_content(model=embed_model, content=query)['embedding']
    db_embs = np.array(st.session_state.db_embeddings)
    q_emb = np.array(query_emb)
    norm_db = np.linalg.norm(db_embs, axis=1)
    norm_q = np.linalg.norm(q_emb)
    if norm_q == 0 or np.any(norm_db == 0): return ""
    scores = np.dot(db_embs, q_emb) / (norm_db * norm_q)
    top_indices = np.argsort(scores)[-top_k:][::-1]
    return "\n\n".join([f"[참고 스타일]\n{st.session_state.db_texts[i]}" for i in top_indices])

# ==========================================
# 3. 메인 UI 구성
# ==========================================
st.set_page_config(page_title="NEIS 세특 AI 어시스턴트", layout="wide")
st.title("📝 NEIS 맞춤형 세특 AI 어시스턴트 (V4: 데이터 누적 저장)")

with st.sidebar:
    st.header("📚 나의 세특 DB 학습")
    db_file = st.file_uploader("과거 우수 세특 엑셀 업로드", type=["xlsx"])
    if db_file and st.button("🧠 문체 학습시키기"):
        df = pd.read_excel(db_file)
        texts = df.iloc[:, 0].dropna().astype(str).tolist()
        result = genai.embed_content(model=embed_model, content=texts)
        st.session_state.db_texts, st.session_state.db_embeddings = texts, result['embedding']
        st.success(f"✅ {len(texts)}개 학습 완료!")
    
    st.divider()
    subject = st.text_input("과목명", value="미적분")
    grade_level = st.text_input("성취도/등급", placeholder="예: A")
    teacher_eval = st.text_area("교사 관찰 팩트 (키워드)", height=100)
    pdf_file = st.file_uploader("학생 보고서 (PDF)", type=["pdf"])

# ==========================================
# 4. 생성 엔진 및 저장 기능
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    if not teacher_eval or not pdf_file:
        st.warning("👈 관찰 팩트와 보고서를 모두 입력해주세요.")
    else:
        with st.spinner("분석 및 검색 중..."):
            pdf_text = ""
            with pdfplumber.open(pdf_file) as pdf:
                pdf_text = "".join([pg.extract_text() for pg in pdf.pages if pg.extract_text()])
            
            # 키워드 추출 및 검색
            kw_p = f"다음 내용에서 최신 기술 동향 검색어 1개만 출력: {teacher_eval} {pdf_text[:500]}"
            kw = model.generate_content(kw_p).text.strip()
            try:
                results = DDGS().text(f"{kw} 최신 기술 연구", max_results=1)
                trend = results[0]['body'] if results else "정보 없음"
            except: trend = "검색 지연"

            # 최종 세특 작성
            ref = find_similar_setek(teacher_eval)
            prompt = f"""
            고교 {subject} 교사로서 NEIS 세특 작성. 
            데이터: 과목({subject}), 등급({grade_level}), 팩트({teacher_eval}), 보고서({pdf_text[:2000]}), 트렌드({trend})
            참고스타일: {ref}
            작성원칙: 450자 내외, 건조한 문체, 하나의 문단, 마크다운 기호 금지.
            """
            response = model.generate_content(prompt)
            st.session_state.current_result = response.text.strip().replace('\n', ' ')
            st.session_state.current_trend = trend

if st.session_state.current_result:
    res_text = st.session_state.current_result
    st.divider()
    st.subheader("🎯 생성된 맞춤형 세특")
    byte_len = get_byte_length(res_text)
    
    if byte_len <= 1500: st.success(f"✅ NEIS 바이트 통가: {byte_len}/1500")
    else: st.error(f"⚠️ 바이트 초과: {byte_len}/1500")
    
    final_text = st.text_area("결과 확인/수정", value=res_text, height=200)

    # --- 💾 저장 버튼 레이아웃 ---
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📊 구글 시트에 즉시 저장", use_container_width=True):
            if GSHEET_SAVE_URL:
                payload = {
                    "subject": subject, "grade": grade_level, 
                    "eval": teacher_eval, "trend": st.session_state.current_trend, 
                    "result": final_text
                }
                try:
                    requests.post(GSHEET_SAVE_URL, json=payload)
                    st.toast("✅ 구글 시트에 누적 저장되었습니다!")
                except: st.error("구글 시트 연결 실패")
            else: st.info("Secrets에 GSHEET_SET_URL을 설정해 주세요.")

    with col2:
        # 엑셀 다운로드 기능
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            pd.DataFrame([{
                "날짜": datetime.now(), "과목": subject, "등급": grade_level, 
                "관찰팩트": teacher_eval, "생성세특": final_text
            }]).to_excel(writer, index=False)
        st.download_button(
            label="📂 엑셀 파일로 개인 소장",
            data=output.getvalue(),
            file_name=f"세특기록_{datetime.now().strftime('%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
