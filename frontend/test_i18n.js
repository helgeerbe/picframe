import fs from 'fs';
const en = JSON.parse(fs.readFileSync('./src/locales/en.json', 'utf8'));
const de = JSON.parse(fs.readFileSync('./src/locales/de.json', 'utf8'));
console.log("en keys:", Object.keys(en));
console.log("de keys:", Object.keys(de));
