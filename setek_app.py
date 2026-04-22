import streamlit as st
import pdfplumber
import google.generativeai as genai

# ==========================================
# 1. API 설정 (기존과 동일하게 Secrets 사용)
# ==========================================
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-2.5-flash")
except Exception as e:
    st.error(f"⚠️ API 키 설정 오류: {e}")

# ==========================================
# 2. 나이스(NEIS) 바이트 계산 함수
# 나이스는 일반적으로 한글/특수문자 3바이트, 영문/숫자/공백 1바이트로 계산합니다.
# ==========================================
def get_byte_length(text):
    return len(text.encode('utf-8'))

# ==========================================
# 3. 메인 UI 구성
# ==========================================
st.set_page_config(page_title="NEIS 세특 AI 어시스턴트", layout="wide")
st.title("📝 NEIS 맞춤형 세특 AI 어시스턴트 (V1)")

# 좌측 입력 폼
with st.sidebar:
    st.header("1. 기본 정보")
    subject = st.text_input("과목명", value="미적분")
    grade_level = st.text_input("성취도/등급", placeholder="예: A (또는 2등급)")
    
    st.header("2. 교사 관찰 팩트")
    teacher_eval = st.text_area(
        "수업 중 관찰 내용 (키워드 위주)", 
        placeholder="예: 미분방정식 실생활 적용 관심 높음. 발표 시 수학적 개념 논리적 전개. 모둠 활동 리더십.",
        height=150
    )
    
    st.header("3. 학생 제출물")
    pdf_file = st.file_uploader("탐구 보고서/수행평가 (PDF)", type=["pdf"])

# ==========================================
# 4. 세특 생성 엔진
# ==========================================
if st.button("🚀 세특 초안 생성하기", type="primary", use_container_width=True):
    if not teacher_eval:
        st.warning("👈 교사 관찰 팩트를 입력해주세요. (AI가 소설을 쓰는 것을 방지합니다)")
    elif not pdf_file:
        st.warning("👈 학생의 탐구 보고서(PDF)를 업로드해주세요.")
    else:
        with st.spinner("학생의 보고서를 분석하고 객관적인 세특을 작성 중입니다..."):
            
            # 1단계: PDF 텍스트 추출 (pdfplumber 사용)
            pdf_text = ""
            with pdfplumber.open(pdf_file) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        pdf_text += extracted + "\n"
            
            # 2단계: AI 티 안 나게 하는 강력한 프롬프트 적용
            prompt = f"""
            당신은 고등학교 {subject} 교사입니다. 아래 데이터를 바탕으로 학교생활기록부(NEIS) 교과세부특기사항(세특)을 작성하세요.

            [데이터]
            - 과목명: {subject}
            - 성취도/등급: {grade_level}
            - 교사 관찰 및 평가: {teacher_eval}
            - 학생 탐구 보고서 발췌: {pdf_text[:3000]}

            [작성 원칙 - 절대 엄수]
            1. 분량: 한글 기준 400자 ~ 450자 사이로 작성 (나이스 1500바이트 제한 기준).
            2. 어투 금지: '놀라운', '탁월한', '완벽하게', '뛰어난 역량을 보임' 등 AI 특유의 과장된 형용사나 감정적 찬양 절대 금지. 철저히 건조하고 객관적인 문체 유지.
            3. 문체: 학생을 관찰한 3인칭 시점의 명사형 종결 또는 '~함', '~모습을 보임', '~설명함' 등의 간결한 종결어미 사용.
            4. 내용 구성: 
               - 도입: 교사가 관찰한 수업 태도 (입력된 팩트 기반)
               - 전개: 학생 보고서의 구체적인 탐구 주제와 알게 된 점 (단순 요약이 아닌, 학생이 어떤 수학적/학문적 접근을 했는지 서술)
               - 결론: 탐구 과정을 통한 성장점 (과장 없이 담백하게)
            5. 포맷: 줄바꿈 없이 하나의 덩어리(문단)로 작성. 마크다운(볼드체 등) 기호 절대 사용 금지.
            """
            
            # 3단계: 결과 생성 및 바이트 검증
            response = model.generate_content(prompt)
            result_text = response.text.strip().replace('\n', ' ') # 혹시 모를 줄바꿈 강제 제거
            byte_len = get_byte_length(result_text)
            
            st.divider()
            st.subheader("🎯 생성된 세특 초안")
            
            # 바이트 상태에 따른 시각적 피드백
            if byte_len <= 1500:
                st.success(f"✅ NEIS 바이트 통과: {byte_len} / 1500 Bytes")
            else:
                st.error(f"⚠️ NEIS 바이트 초과: {byte_len} / 1500 Bytes (문장을 조금 다듬어주세요)")
                
            st.text_area("수정 후 나이스에 바로 복사하세요:", value=result_text, height=250)