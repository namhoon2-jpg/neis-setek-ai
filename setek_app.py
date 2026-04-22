import streamlit as st
import pdfplumber
import google.generativeai as genai
import pandas as pd
import numpy as np
from duckduckgo_search import DDGS

# ==========================================
# 1. API 설정
# ==========================================
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.5-flash")
    embed_model = "models/text-embedding-004" 
except Exception as e:
    st.error(f"⚠️ API 키 설정 오류: {e}")

# ==========================================
# 2. 세션 상태 (DB 기억 장치) 초기화
# ==========================================
if "db_texts" not in st.session_state:
    st.session_state.db_texts = []
if "db_embeddings" not in st.session_state:
    st.session_state.db_embeddings = []

def get_byte_length(text):
    return len(text.encode('utf-8'))

# ==========================================
# 3. RAG: 유사도 검색 함수
# ==========================================
def find_similar_setek(query, top_k=2):
    if not st.session_state.db_texts:
        return ""
    
    query_emb = genai.embed_content(model=embed_model, content=query)['embedding']
    db_embs = np.array(st.session_state.db_embeddings)
    q_emb = np.array(query_emb)
    
    # 0으로 나누는 오류 방지
    norm_db = np.linalg.norm(db_embs, axis=1)
    norm_q = np.linalg.norm(q_emb)
    if norm_q == 0 or np.any(norm_db == 0): return ""
    
    scores = np.dot(db_embs, q_emb) / (norm_db * norm_q)
    top_indices = np.argsort(scores)[-top_k:][::-1]
    similar_texts = [st.session_state.db_texts[i] for i in top_indices]
    
    return "\n\n".join([f"[과거 선생님의 우수 세특 예시 {i+1}]\n{text}" for i, text in enumerate(similar_texts)])

# ==========================================
# 4. 메인 UI 구성
# ==========================================
st.set_page_config(page_title="NEIS 세특 AI 어시스턴트", layout="wide")
st.title("📝 NEIS 맞춤형 세특 AI 어시스턴트 (V3: 실시간 웹 검색)")

with st.sidebar:
    st.header("📚 나의 세특 DB 학습시키기")
    db_file = st.file_uploader("과거 우수 세특 엑셀 업로드", type=["xlsx"])
    
    if db_file and st.button("🧠 AI에게 내 문체 학습시키기"):
        with st.spinner("선생님의 문체를 벡터화하여 학습 중입니다..."):
            df = pd.read_excel(db_file)
            texts = df.iloc[:, 0].dropna().astype(str).tolist()
            result = genai.embed_content(model=embed_model, content=texts)
            
            st.session_state.db_texts = texts
            st.session_state.db_embeddings = result['embedding']
            st.success(f"✅ {len(texts)}개의 세특 학습 완료!")
            
    st.divider()
    
    st.header("1. 기본 정보")
    subject = st.text_input("과목명", value="미적분")
    grade_level = st.text_input("성취도/등급", placeholder="예: A (또는 2등급)")
    
    st.header("2. 교사 관찰 팩트")
    teacher_eval = st.text_area("수업 중 관찰 내용 (키워드 위주)", height=150)
    
    st.header("3. 학생 제출물")
    pdf_file = st.file_uploader("탐구 보고서/수행평가 (PDF)", type=["pdf"])

# ==========================================
# 5. 세특 생성 엔진 (웹 검색 탑재)
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    if not teacher_eval:
        st.warning("👈 교사 관찰 팩트를 입력해주세요.")
    elif not pdf_file:
        st.warning("👈 학생의 탐구 보고서(PDF)를 업로드해주세요.")
    else:
        with st.spinner("1/3: 학생 보고서를 분석 중입니다..."):
            pdf_text = ""
            with pdfplumber.open(pdf_file) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted: pdf_text += extracted + "\n"
        
        with st.spinner("2/3: 최신 학술 동향을 웹에서 팩트체크 중입니다..."):
            # AI 스스로 학생 보고서에서 핵심 키워드 1개 도출
            keyword_prompt = f"다음 학생의 탐구 내용에서 최신 학술/기술 동향을 검색할 수 있는 가장 핵심적인 명사 키워드 1개만 출력해. 기호 없이 단어만 출력.\n내용: {teacher_eval} {pdf_text[:500]}"
            search_keyword = model.generate_content(keyword_prompt).text.strip()
            
            # DuckDuckGo를 활용한 실시간 웹 검색
            try:
                results = DDGS().text(f"{search_keyword} 최신 기술 동향 연구", max_results=2)
                trend_info = "\n".join([f"- {res['title']}: {res['body']}" for res in results])
                st.info(f"🌐 웹 검색 완료: '{search_keyword}' 관련 최신 동향을 세특에 반영합니다.")
            except Exception as e:
                trend_info = "검색 서버 지연으로 최신 동향을 가져오지 못했습니다."
                st.info("🌐 웹 검색 지연: 기본 텍스트 기반으로 세특을 작성합니다.")

        with st.spinner("3/3: 선생님의 문체를 모방하여 세특을 최종 작성 중입니다..."):
            reference_styles = find_similar_setek(teacher_eval)
            rag_instruction = ""
            if reference_styles:
                rag_instruction = f"""
                [선생님의 과거 작성 스타일 - 완벽 모방 필수!]
                아래 교사가 과거에 작성했던 세특 예시들의 '어투', '전문 용어 활용', '종결어미'를 철저히 분석하고 동일한 톤앤매너로 작성하세요.
                {reference_styles}
                """
            
            prompt = f"""
            당신은 고등학교 {subject} 교사입니다. 아래 데이터를 바탕으로 학교생활기록부(NEIS) 교과세부특기사항(세특)을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도/등급: {grade_level}
            - 교사 관찰 및 평가: {teacher_eval}
            - 학생 탐구 보고서 발췌: {pdf_text[:3000]}
            - 검색된 최신 동향(팩트체크): {trend_info}

            {rag_instruction}

            [작성 원칙 - 절대 엄수]
            1. 분량: 한글 기준 400자 ~ 450자 사이로 작성 (나이스 1500바이트 제한 기준).
            2. 어투 금지: '놀라운', '탁월한' 등 AI 특유의 과장된 형용사나 감정적 찬양 절대 금지. 건조하고 객관적인 문체 유지.
            3. 트렌드 융합: 학생의 탐구 내용이 [검색된 최신 동향]과 어떻게 맞닿아 있는지, 교사로서 학생의 학문적 시야의 깊이를 평가하는 문장을 1줄 반드시 포함할 것.
            4. 포맷: 줄바꿈 없이 하나의 덩어리(문단)로 작성. 마크다운 기호 절대 금지.
            """
            
            response = model.generate_content(prompt)
            result_text = response.text.strip().replace('\n', ' ')
            byte_len = get_byte_length(result_text)
            
            st.divider()
            st.subheader("🎯 생성된 맞춤형 세특 초안")
            
            if byte_len <= 1500: st.success(f"✅ NEIS 바이트 통과: {byte_len} / 1500 Bytes")
            else: st.error(f"⚠️ NEIS 바이트 초과: {byte_len} / 1500 Bytes")
                
            st.text_area("수정 후 나이스에 바로 복사하세요:", value=result_text, height=250)
