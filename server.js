const express = require('express');
const session = require('express-session');
const path = require('path');
const { google } = require('googleapis');
const { Storage } = require('@google-cloud/storage');
const sharp = require('sharp');

const app = express();
const PORT = Number(process.env.PORT || 5000);

const SESSION_SECRET = process.env.SECRET_KEY || 'kdn_secret_key';
const USERS_SHEET_KEY = process.env.GOOGLE_USERS_SHEET_KEY;
const RECORDS_SHEET_KEY = process.env.GOOGLE_RECORDS_SHEET_KEY;
const GCS_BUCKET_NAME = process.env.GCS_BUCKET_NAME || 'amimms-receipts';
const GOOGLE_CREDENTIALS_JSON = process.env.GOOGLE_CREDENTIALS_JSON;

if (!GOOGLE_CREDENTIALS_JSON) {
  throw new Error('GOOGLE_CREDENTIALS_JSON 환경 변수가 설정되지 않았습니다.');
}
if (!USERS_SHEET_KEY || !RECORDS_SHEET_KEY) {
  throw new Error('GOOGLE_USERS_SHEET_KEY 또는 GOOGLE_RECORDS_SHEET_KEY 환경 변수가 설정되지 않았습니다.');
}

const credentials = JSON.parse(GOOGLE_CREDENTIALS_JSON);
const auth = new google.auth.GoogleAuth({
  credentials,
  scopes: ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/devstorage.read_write'],
});
const sheets = google.sheets({ version: 'v4', auth });
const storage = new Storage({ credentials });

app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use('/public', express.static(path.join(__dirname, 'public')));
app.use('/static', express.static(path.join(__dirname, 'static')));
app.use(express.urlencoded({ extended: true, limit: '15mb' }));
app.use(express.json({ limit: '15mb' }));
app.use(session({
  secret: SESSION_SECRET,
  resave: false,
  saveUninitialized: false,
  cookie: {
    httpOnly: true,
    sameSite: 'lax',
    secure: process.env.NODE_ENV === 'production' && process.env.FORCE_HTTPS === 'true',
    maxAge: 1000 * 60 * 60 * 10,
  },
}));

function requireLogin(req, res, next) {
  if (!req.session.loggedIn) return res.redirect('/');
  next();
}

function requireAdmin(req, res, next) {
  if (!req.session.loggedIn) return res.status(403).json({ error: '로그인 필요' });
  if (req.session.authority !== 'y') return res.status(403).json({ error: '권한 없음' });
  next();
}

function normalizeCell(value) {
  return value === undefined || value === null ? '' : String(value).trim();
}

function rowsToObjects(values = []) {
  if (!values.length) return [];
  const headers = values[0].map(normalizeCell);
  return values.slice(1).filter(row => row.some(cell => normalizeCell(cell))).map(row => {
    const obj = {};
    headers.forEach((h, index) => {
      if (h) obj[h] = normalizeCell(row[index]);
    });
    return obj;
  });
}

async function getSheetObjects(spreadsheetId) {
  const result = await sheets.spreadsheets.values.get({ spreadsheetId, range: 'A:Z' });
  return rowsToObjects(result.data.values || []);
}

async function appendRecord(row) {
  await sheets.spreadsheets.values.append({
    spreadsheetId: RECORDS_SHEET_KEY,
    range: 'A:H',
    valueInputOption: 'USER_ENTERED',
    requestBody: { values: [row] },
  });
}

function asArray(value) {
  if (Array.isArray(value)) return value;
  if (value === undefined || value === null) return [];
  return [value];
}

function collectMaterials(body) {
  const comms = asArray(body['통신방식']);
  const categories = asArray(body['구분']);
  const newOld = asArray(body['신철']);
  const qtys = asArray(body['수량']);
  const boxes = asArray(body['박스번호']);

  return comms.map((_, index) => ({
    '통신방식': normalizeCell(comms[index]),
    '구분': normalizeCell(categories[index]),
    '신철': normalizeCell(newOld[index]),
    '수량': normalizeCell(qtys[index]),
    '박스번호': normalizeCell(boxes[index]),
  })).filter(item => item['통신방식'] || item['구분'] || item['수량'] || item['박스번호']);
}

function groupSummary(records) {
  const map = new Map();
  records.forEach(row => {
    const key = `${row['통신방식'] || ''}|${row['구분'] || ''}`;
    if (!map.has(key)) {
      map.set(key, { '통신방식': row['통신방식'] || '', '구분': row['구분'] || '', '합계': 0, '박스수': 0 });
    }
    const target = map.get(key);
    target['합계'] += Number(row['수량']) || 0;
    target['박스수'] += 1;
  });
  return Array.from(map.values()).sort((a, b) => `${a['통신방식']} ${a['구분']}`.localeCompare(`${b['통신방식']} ${b['구분']}`, 'ko'));
}

function escapeXml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function signatureImage(dataUrl) {
  if (!dataUrl || !String(dataUrl).startsWith('data:image')) return '';
  return String(dataUrl);
}

function receiptSvg(materials, giver, receiver, giverSign, receiverSign) {
  const width = 1240;
  const height = 1754;
  const rowHeight = 60;
  const startY = 360;
  const rows = materials.map((m, index) => {
    const y = startY + rowHeight * (index + 1);
    return `
      <rect x="80" y="${y}" width="1020" height="${rowHeight}" fill="#fff" stroke="#202938" stroke-width="1.4"/>
      <text x="100" y="${y + 39}" class="cell">${escapeXml(m['통신방식'])}</text>
      <text x="340" y="${y + 39}" class="cell">${escapeXml(m['구분'])}</text>
      <text x="580" y="${y + 39}" class="cell">${escapeXml(m['신철'])}</text>
      <text x="780" y="${y + 39}" class="cell">${escapeXml(m['수량'])}</text>
      <text x="960" y="${y + 39}" class="cell">${escapeXml(m['박스번호'])}</text>`;
  }).join('');
  const footerLineY = height - 180;
  const textY = footerLineY - 70;
  const today = new Date().toISOString().slice(0, 10);
  const giverImg = signatureImage(giverSign);
  const receiverImg = signatureImage(receiverSign);

  return `<?xml version="1.0" encoding="UTF-8"?>
  <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
    <style>
      .title{font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif;font-size:64px;font-weight:800;fill:#111827;}
      .label{font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif;font-size:30px;font-weight:800;fill:#111827;}
      .cell{font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif;font-size:27px;font-weight:700;fill:#111827;}
      .foot{font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif;font-size:26px;font-weight:600;fill:#667085;}
    </style>
    <rect width="100%" height="100%" fill="#ffffff"/>
    <rect x="50" y="40" width="1110" height="1664" rx="18" fill="none" stroke="#202938" stroke-width="3"/>
    <text x="470" y="158" class="title">자재 인수증</text>
    <text x="100" y="260" class="label">작성일자: ${today}</text>
    <rect x="80" y="${startY}" width="1020" height="${rowHeight}" fill="#e8f0fe" stroke="#202938" stroke-width="1.6"/>
    <text x="100" y="${startY + 39}" class="label">통신방식</text>
    <text x="340" y="${startY + 39}" class="label">구분</text>
    <text x="580" y="${startY + 39}" class="label">신철</text>
    <text x="780" y="${startY + 39}" class="label">수량</text>
    <text x="960" y="${startY + 39}" class="label">박스번호</text>
    ${rows}
    <line x1="80" y1="${footerLineY}" x2="1160" y2="${footerLineY}" stroke="#d0d5dd" stroke-width="2"/>
    <text x="180" y="${textY}" class="label">주는 사람: ${escapeXml(giver)} (인)</text>
    <text x="700" y="${textY}" class="label">받는 사람: ${escapeXml(receiver)} (인)</text>
    ${giverImg ? `<image href="${giverImg}" x="380" y="${textY - 62}" width="200" height="90" preserveAspectRatio="xMidYMid meet"/>` : ''}
    ${receiverImg ? `<image href="${receiverImg}" x="940" y="${textY - 62}" width="200" height="90" preserveAspectRatio="xMidYMid meet"/>` : ''}
    <text x="385" y="1638" class="foot">한전KDN 주식회사 | AMI 자재관리시스템</text>
  </svg>`;
}

async function uploadReceipt(buffer, fileName) {
  const bucket = storage.bucket(GCS_BUCKET_NAME);
  const file = bucket.file(fileName);
  await file.save(buffer, { contentType: 'image/jpeg', resumable: false });
  const [url] = await file.getSignedUrl({
    action: 'read',
    expires: Date.now() + 365 * 24 * 60 * 60 * 1000,
  });
  return url;
}

async function generateReceipt(materials, giver, receiver, giverSign, receiverSign) {
  const svg = receiptSvg(materials, giver, receiver, giverSign, receiverSign);
  const buffer = await sharp(Buffer.from(svg)).jpeg({ quality: 95 }).toBuffer();
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
  const safeReceiver = String(receiver || 'unknown').replace(/[\\/:*?"<>|\s]+/g, '_');
  const fileName = `receipt_${safeReceiver}_${stamp}.jpg`;
  return uploadReceipt(buffer, fileName);
}

app.get('/', async (req, res) => {
  if (req.session.loggedIn) return res.redirect('/menu');
  res.render('login', { error: null });
});

app.post('/', async (req, res) => {
  try {
    const userId = normalizeCell(req.body.user_id);
    const password = normalizeCell(req.body.password);
    const users = await getSheetObjects(USERS_SHEET_KEY);
    const user = users.find(item => normalizeCell(item.ID) === userId);
    if (user && normalizeCell(user.PASSWORD) === password) {
      req.session.loggedIn = true;
      req.session.userId = userId;
      req.session.authority = normalizeCell(user.AUTHORITY);
      return res.redirect('/menu');
    }
    return res.status(401).render('login', { error: '아이디 또는 비밀번호가 잘못되었습니다.' });
  } catch (error) {
    console.error(error);
    return res.status(500).render('login', { error: '로그인 처리 중 오류가 발생했습니다.' });
  }
});

app.get('/menu', requireLogin, (req, res) => {
  res.render('menu', { userId: req.session.userId, authority: req.session.authority });
});

app.get('/form', requireLogin, (req, res) => {
  if (req.query.new === '1') req.session.materials = [];
  res.render('form', { materials: req.session.materials || [] });
});

app.post('/form', requireLogin, (req, res) => {
  const materials = collectMaterials(req.body);
  req.session.materials = materials;
  res.redirect('/confirm');
});

app.get('/confirm', requireLogin, (req, res) => {
  res.render('confirm', { materials: req.session.materials || [], loggedUser: req.session.userId });
});

app.post('/confirm', requireLogin, async (req, res) => {
  try {
    const materials = req.session.materials || [];
    if (!materials.length) return res.redirect('/form?new=1');

    const giver = normalizeCell(req.body.giver);
    const receiver = normalizeCell(req.body.receiver || req.session.userId);
    const giverSign = req.body.giver_sign;
    const receiverSign = req.body.receiver_sign;
    const receiptLink = await generateReceipt(materials, giver, receiver, giverSign, receiverSign);
    const now = new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Seoul' }).replace('T', ' ');

    for (const m of materials) {
      await appendRecord([
        m['통신방식'] || '',
        m['구분'] || '',
        giver,
        receiver,
        m['신철'] || '',
        m['수량'] || '',
        m['박스번호'] || '',
        now,
      ]);
    }

    req.session.lastReceipt = receiptLink;
    req.session.lastReceiver = receiver;
    res.render('result', { receiptLink });
  } catch (error) {
    console.error(error);
    res.status(500).render('result', { receiptLink: null, error: '인수증 생성 중 오류가 발생했습니다.' });
  }
});

app.get('/summary', requireLogin, async (req, res) => {
  try {
    const records = await getSheetObjects(RECORDS_SHEET_KEY);
    const filtered = records.filter(row => normalizeCell(row['받는사람']) === req.session.userId);
    const summaryData = groupSummary(filtered);
    res.render('summary', { summaryData, message: summaryData.length ? null : '등록된 자재 데이터가 없습니다.' });
  } catch (error) {
    console.error(error);
    res.status(500).render('summary', { summaryData: [], message: '데이터 조회 중 오류가 발생했습니다.' });
  }
});

app.get('/admin_summary', requireLogin, (req, res) => {
  if (req.session.authority !== 'y') return res.status(403).send('접근 권한이 없습니다.');
  res.render('admin_summary', { userId: req.session.userId });
});

app.get('/api/admin_data', requireAdmin, async (req, res) => {
  try {
    const records = await getSheetObjects(RECORDS_SHEET_KEY);
    const data = records.filter(row => normalizeCell(row['주는사람']) === req.session.userId);
    res.json({ data });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: '데이터 조회 오류' });
  }
});

app.get('/download_receipt', requireLogin, async (req, res) => {
  try {
    const receiptUrl = req.session.lastReceipt;
    const receiver = req.session.lastReceiver || 'unknown';
    if (!receiptUrl) return res.status(404).send('인수증 파일을 찾을 수 없습니다.');

    const response = await fetch(receiptUrl);
    if (!response.ok) return res.status(500).send('인수증 파일을 다운로드할 수 없습니다.');
    const arrayBuffer = await response.arrayBuffer();
    const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14);
    res.setHeader('Content-Type', 'image/jpeg');
    res.setHeader('Content-Disposition', `attachment; filename="receipt_${encodeURIComponent(receiver)}_${stamp}.jpg"`);
    res.send(Buffer.from(arrayBuffer));
  } catch (error) {
    console.error(error);
    res.status(500).send('파일 다운로드 중 오류가 발생했습니다.');
  }
});

app.get('/logout', (req, res) => {
  req.session.destroy(() => res.redirect('/'));
});

app.listen(PORT, '0.0.0.0', () => {
  console.log(`AMIMMS JavaScript server running on 0.0.0.0:${PORT}`);
});
