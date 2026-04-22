import streamlit as st
import pdfplumber
import google.generativeai as genai
import pandas as pd
import numpy as np
import io
import requests
from datetime import datetime
from duckduckgo_search import DDGS

# ==========================================
# 0. 설정 (비밀번호 및 시트 연결)
# ==========================================
APP_PASSWORD = "2848" 

# 구글 시트를 '웹에 게시(CSV)'한 URL을 Secrets에 넣거나 여기에 직접 넣으세요.
# 예: GSHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/.../pub?output=csv"
GSHEET_CSV_URL = st.secrets.get("GSHEET_KNOWLEDGE_URL", "")

st.set_page_config(page_title="NEIS 세특 AI 어시스턴트", layout="wide")

# ==========================================
# 1. 로그인 및 권한 확인
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.title("🔒 교과세특 AI 어시스턴트 로그인")
    pwd_input = st.text_input("비밀번호", type="password")
    if st.button("입장하기"):
        if pwd_input == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("⚠️ 비밀번호가 틀렸습니다.")
    st.stop()

# ==========================================
# 2. AI 및 세션 상태 초기화
# ==========================================
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.5-flash")
    embed_model = "models/text-embedding-004" 
except Exception as e:
    st.error(f"⚠️ API 설정 오류: {e}")

if "db_texts" not in st.session_state: st.session_state.db_texts = []
if "db_embeddings" not in st.session_state: st.session_state.db_embeddings = []
if "current_result" not in st.session_state: st.session_state.current_result = ""

# ==========================================
# 3. 핵심 함수: 구글 시트 지식 동기화
# ==========================================
def sync_with_gsheet():
    if not GSHEET_CSV_URL:
        st.sidebar.warning("🔗 구글 시트 URL이 설정되지 않았습니다.")
        return
    
    try:
        # 구글 시트에서 데이터 가져오기
        response = requests.get(GSHEET_CSV_URL)
        df = pd.read_csv(io.StringIO(response.text))
        texts = df.iloc[:, 0].dropna().astype(str).tolist()
        
        # AI 임베딩 생성 및 저장
        result = genai.embed_content(model=embed_model, content=texts)
        st.session_state.db_texts = texts
        st.session_state.db_embeddings = result['embedding']
        return len(texts)
    except Exception as e:
        st.sidebar.error(f"동기화 실패: {e}")
        return 0

def find_similar_knowledge(query, top_k=3):
    if not st.session_state.db_texts: return ""
    query_emb = genai.embed_content(model=embed_model, content=query)['embedding']
    db_embs = np.array(st.session_state.db_embeddings)
    q_emb = np.array(query_emb)
    norm_db = np.linalg.norm(db_embs, axis=1)
    norm_q = np.linalg.norm(q_emb)
    if norm_q == 0 or np.any(norm_db == 0): return ""
    scores = np.dot(db_embs, q_emb) / (norm_db * norm_q)
    top_indices = np.argsort(scores)[-min(top_k, len(texts)):][::-1]
    return "\n\n".join([st.session_state.db_texts[idx] for idx in top_indices])

# ==========================================
# 4. 화면 구성
# ==========================================
st.title("📝 NEIS 세특 AI 어시스턴트 (V6: 구글 시트 동기화)")

# 사이드바에서 지식 관리
with st.sidebar:
    st.header("🔄 지식 저장소 관리")
    if st.button("🌐 구글 시트 지식 최신화", use_container_width=True):
        count = sync_with_gsheet()
        if count > 0: st.success(f"{count}개의 지식을 동기화했습니다!")

    if not st.session_state.db_texts:
        st.warning("⚠️ 현재 학습된 지식이 없습니다. 위 버튼을 눌러 시트와 연결하세요.")
    else:
        st.info(f"🧠 현재 기억 중인 지식: {len(st.session_state.db_texts)}개")

    st.divider()
    subject = st.text_input("과목명", placeholder="예: 미적분")
    grade_level = st.text_input("성취도", placeholder="예: A")
    teacher_eval = st.text_area("관찰 팩트", height=100)
    pdf_file = st.file_uploader("보고서(PDF)", type=["pdf"])

# 앱 구동 시 지식이 비어있으면 자동 동기화 시도 (선택 사항)
if st.session_state.authenticated and not st.session_state.db_texts and GSHEET_CSV_URL:
    sync_with_gsheet()

# [이후 생성 엔진 로직은 V5와 동일...]
# (길이 관계상 생략하지만, V5의 생성 엔진 코드를 그대로 붙여넣으시면 됩니다.)
