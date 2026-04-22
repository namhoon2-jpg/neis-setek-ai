import streamlit as st
import pdfplumber
import google.generativeai as genai
import pandas as pd
import numpy as np
import io
from datetime import datetime
from duckduckgo_search import DDGS

# ==========================================
# 0. 앱 비밀번호 설정 (여기를 수정하세요)
# ==========================================
APP_PASSWORD = "2848" # 동료 선생님들과 공유할 비밀번호를 여기에 적어주세요.

st.set_page_config(page_title="NEIS 세특 AI 어시스턴트", layout="wide")

# ==========================================
# 1. 로그인 (비밀번호 확인) 로직
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

# 인증되지 않은 경우 로그인 화면만 표시하고 아래 코드는 실행하지 않음
if not st.session_state.authenticated:
    st.title("🔒 교과세특 AI 어시스턴트 로그인")
    st.info("인가된 교직원만 사용할 수 있는 시스템입니다. 동료 선생님들께 공유받은 비밀번호를 입력해주세요.")
    
    pwd_input = st.text_input("비밀번호", type="password")
    if st.button("입장하기", type="primary"):
        if pwd_input == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun() # 비밀번호가 맞으면 화면을 새로고침하여 본 앱으로 진입
        else:
            st.error("⚠️ 비밀번호가 일치하지 않습니다.")
    st.stop() # 비밀번호 통과 전까지는 여기서 시스템 멈춤

# ==========================================
# 2. API 설정 (이하 본문 코드는 기존과 100% 동일)
# ==========================================
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.5-flash")
    embed_model = "models/text-embedding-004" 
except Exception as e:
    st.error(f"⚠️ 설정 오류: {e}")

if "db_texts" not in st.session_state: st.session_state.db_texts = []
if "db_embeddings" not in st.session_state: st.session_state.db_embeddings = []
if "current_result" not in st.session_state: st.session_state.current_result = ""
if "current_trend" not in st.session_state: st.session_state.current_trend = ""

def get_byte_length(text):
    return len(text.encode('utf-8'))

# ==========================================
# 3. RAG & 웹 검색 함수
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
# 4. 메인 UI 구성
# ==========================================
st.title("📝 NEIS 맞춤형 세특 AI 어시스턴트")
st.info("이 시스템은 입력된 데이터를 서버에 저장하지 않습니다. 작업이 끝나면 반드시 엑셀로 다운로드하여 개인 PC에 보관하세요.")

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
# 5. 생성 엔진
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
    
    if byte_len <= 1500: st.success(f"✅ NEIS 바이트 통과: {byte_len}/1500")
    else: st.error(f"⚠️ 바이트 초과: {byte_len}/1500")
    
    final_text = st.text_area("결과 확인/수정", value=res_text, height=200)

    # --- 💾 저장 로직 (공유용 로컬 다운로드만 제공) ---
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame([{
            "날짜": datetime.now().strftime('%Y-%m-%d %H:%M'), 
            "과목": subject, 
            "등급": grade_level, 
            "관찰팩트": teacher_eval, 
            "생성세특": final_text
        }]).to_excel(writer, index=False)
        
    st.download_button(
        label="📂 작성된 세특 엑셀로 다운로드 (개인 PC 보관)",
        data=output.getvalue(),
        file_name=f"세특기록_{datetime.now().strftime('%m%d_%H%M')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )
