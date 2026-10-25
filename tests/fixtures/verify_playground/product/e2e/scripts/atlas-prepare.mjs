import fs from 'fs';
fs.mkdirSync('.verify', { recursive: true });
fs.writeFileSync('.verify/last-prepare', new Date().toISOString());
console.log('playground prepared');
