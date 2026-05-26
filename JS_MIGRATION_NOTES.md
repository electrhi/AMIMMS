# AMIMMS JavaScript Migration

이 브랜치는 기존 Python Flask 기반 AMIMMS를 JavaScript Node.js Express 기반으로 전환한 작업입니다.

## 유지한 기능

- Google Sheets 기반 로그인
- 세션 기반 인증
- 자재 인수증 다중 입력
- 통신방식별 구분 선택
- 확인 화면
- PC 및 모바일 서명 캔버스
- 인수증 이미지 생성
- Google Cloud Storage 업로드
- 인수증 다운로드
- 사용자별 누적 자재 현황
- 관리자 종합관리표 API 및 화면

## 환경변수

기존 환경변수명을 유지했습니다.

- SECRET_KEY
- GOOGLE_CREDENTIALS_JSON
- GOOGLE_USERS_SHEET_KEY
- GOOGLE_RECORDS_SHEET_KEY
- GCS_BUCKET_NAME

## 실행 방식

- Node.js 20 이상
- Start command: npm start
- Procfile: web: npm start

## 참고

기존 Python 파일은 롤백 참고용으로 보존했습니다. 이 브랜치를 배포하면 server.js가 실제 실행 진입점입니다.
