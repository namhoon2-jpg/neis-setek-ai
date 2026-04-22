import streamlit as st
import pdfplumber
import google.generativeai as genai
import pandas as pd
import numpy as np

# ==========================================
# 1. API 설정
# ==========================================
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.5-flash")
    # 텍스트를 벡터(숫자)로 바꿔주는 임베딩 모델
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
    
    # 1. 현재 입력된 쿼리(학생 팩트)를 벡터로 변환
    query_emb = genai.embed_content(model=embed_model, content=query)['embedding']
    
    # 2. 기존 DB와 코사인 유사도(Cosine Similarity) 계산
    db_embs = np.array(st.session_state.db_embeddings)
    q_emb = np.array(query_emb)
    scores = np.dot(db_embs, q_emb) / (np.linalg.norm(db_embs, axis=1) * np.linalg.norm(q_emb))
    
    # 3. 가장 점수가 높은 상위 top_k개 추출
    top_indices = np.argsort(scores)[-top_k:][::-1]
    similar_texts = [st.session_state.db_texts[i] for i in top_indices]
    
    return "\n\n".join([f"[과거 선생님의 우수 세특 예시 {i+1}]\n{text}" for i, text in enumerate(similar_texts)])

# ==========================================
# 4. 메인 UI 구성
# ==========================================
st.set_page_config(page_title="NEIS 세특 AI 어시스턴트", layout="wide")
st.title("📝 NEIS 맞춤형 세특 AI 어시스턴트 (V2: RAG 탑재)")

# --- 좌측 사이드바 ---
with st.sidebar:
    st.header("📚 나의 세특 DB 학습시키기")
    st.info("A열에 '세특 내용'이 들어간 엑셀(.xlsx)을 올려주세요. (최정예 예시 20~50개 권장)")
    db_file = st.file_uploader("과거 우수 세특 엑셀 업로드", type=["xlsx"])
    
    if db_file and st.button("🧠 AI에게 내 문체 학습시키기"):
        with st.spinner("선생님의 문체를 벡터화하여 학습 중입니다..."):
            df = pd.read_excel(db_file)
            # 엑셀의 첫 번째 열 데이터를 문자열 리스트로 변환
            texts = df.iloc[:, 0].dropna().astype(str).tolist()
            
            # 구글 임베딩 API로 텍스트들을 벡터로 일괄 변환
            result = genai.embed_content(model=embed_model, content=texts)
            
            st.session_state.db_texts = texts
            st.session_state.db_embeddings = result['embedding']
            st.success(f"✅ {len(texts)}개의 세특 학습 완료! 이제 선생님의 문체를 모방합니다.")
            
    st.divider()
    
    st.header("1. 기본 정보")
    subject = st.text_input("과목명", value="미적분")
    grade_level = st.text_input("성취도/등급", placeholder="예: A (또는 2등급)")
    
    st.header("2. 교사 관찰 팩트")
    teacher_eval = st.text_area("수업 중 관찰 내용 (키워드 위주)", height=150)
    
    st.header("3. 학생 제출물")
    pdf_file = st.file_uploader("탐구 보고서/수행평가 (PDF)", type=["pdf"])

# ==========================================
# 5. 세특 생성 엔진
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    if not teacher_eval:
        st.warning("👈 교사 관찰 팩트를 입력해주세요.")
    elif not pdf_file:
        st.warning("👈 학생의 탐구 보고서(PDF)를 업로드해주세요.")
    else:
        with st.spinner("보고서를 분석하고 선생님의 과거 문체를 모방하여 작성 중입니다..."):
            
            # 1단계: PDF 텍스트 추출
            pdf_text = ""
            with pdfplumber.open(pdf_file) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted: pdf_text += extracted + "\n"
            
            # 2단계: RAG - DB에서 가장 비슷한 과거 세특 찾아오기
            reference_styles = find_similar_setek(teacher_eval)
            rag_instruction = ""
            if reference_styles:
                rag_instruction = f"""
                [선생님의 과거 작성 스타일 - 완벽 모방 필수!]
                아래는 교사가 과거에 직접 작성했던 세특 예시들입니다. 이 예시들의 '어투', '문장 길이', '전문 용어 활용 방식', '문장 끝맺음(~함, ~임)'을 철저하게 분석하고 완벽하게 똑같은 톤앤매너로 작성하세요. AI 특유의 과장된 표현은 배제하십시오.
                
                {reference_styles}
                """
            
            # 3단계: 프롬프트 조합
            prompt = f"""
            당신은 고등학교 {subject} 교사입니다. 아래 데이터를 바탕으로 학교생활기록부(NEIS) 교과세부특기사항(세특)을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도/등급: {grade_level}
            - 교사 관찰 및 평가: {teacher_eval}
            - 학생 탐구 보고서 발췌: {pdf_text[:3000]}

            {rag_instruction}

            [작성 원칙 - 절대 엄수]
            1. 분량: 한글 기준 400자 ~ 450자 사이로 작성 (나이스 1500바이트 제한 기준).
            2. 어투 금지: '놀라운', '탁월한', '완벽하게' 등 AI 특유의 과장된 형용사나 감정적 찬양 절대 금지. 철저히 건조하고 객관적인 문체 유지.
            3. 포맷: 줄바꿈 없이 하나의 덩어리(문단)로 작성. 마크다운(볼드체 등) 기호 절대 사용 금지.
            """
            
            # 4단계: 결과 생성 및 바이트 검증
            response = model.generate_content(prompt)
            result_text = response.text.strip().replace('\n', ' ')
            byte_len = get_byte_length(result_text)
            
            st.divider()
            st.subheader("🎯 생성된 맞춤형 세특 초안")
            
            if byte_len <= 1500: st.success(f"✅ NEIS 바이트 통과: {byte_len} / 1500 Bytes")
            else: st.error(f"⚠️ NEIS 바이트 초과: {byte_len} / 1500 Bytes")
                
            st.text_area("수정 후 나이스에 바로 복사하세요:", value=result_text, height=250)
