'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

function pdfToText(buf) {
  const tmp = path.join(os.tmpdir(), `econ-cal-${process.pid}-${Date.now()}.pdf`);
  try {
    fs.writeFileSync(tmp, buf);
    return execFileSync('pdftotext', ['-layout', tmp, '-'], { encoding: 'utf8', maxBuffer: 8_000_000 });
  } finally {
    try { fs.unlinkSync(tmp); } catch (_) {}
  }
}

module.exports = { pdfToText };
