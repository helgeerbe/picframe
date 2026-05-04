import fs from 'fs';
const schema = JSON.parse(fs.readFileSync('./src/configSchema.json', 'utf8'));
console.log(Object.keys(schema));
