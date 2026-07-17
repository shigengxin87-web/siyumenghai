import { readFile, writeFile } from 'node:fs/promises';
import { extname, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const memberView = resolve(root, 'member-view');
const membersPath = resolve(memberView, 'members.json');
const appPath = resolve(memberView, 'app.js');

const payload = JSON.parse(await readFile(membersPath, 'utf8'));
const embedded = await Promise.all(payload.members.map(async (member, index) => {
  if (!member.avatar) return { name: member.name, order: index + 1, avatar: null };

  const relativePath = member.avatar.split('?', 1)[0].replace(/^\.\//, '');
  const avatarPath = resolve(memberView, relativePath);
  const extension = extname(avatarPath).toLowerCase();
  const mime = extension === '.png' ? 'image/png' : extension === '.gif' ? 'image/gif' : 'image/jpeg';
  const avatar = `data:${mime};base64,${(await readFile(avatarPath)).toString('base64')}`;
  return { name: member.name, order: index + 1, avatar };
}));

const app = await readFile(appPath, 'utf8');
const memberBlock = /(?:\/\/ Embedded so shallow server deployments cannot lose member data or avatar files\.\n)?let members = \[[\s\S]*?\nlet membersUpdatedAt = [^;]+;/;

if (!memberBlock.test(app)) {
  throw new Error('Could not find the member directory block in member-view/app.js');
}

const replacement = `// Embedded so shallow server deployments cannot lose member data or avatar files.\nlet members = ${JSON.stringify(embedded, null, 2)};\nlet membersUpdatedAt = ${JSON.stringify(payload.updatedAt || null)};`;
const nextApp = app.replace(memberBlock, replacement);

await writeFile(appPath, nextApp);
console.log(`Embedded ${embedded.length} members in member-view/app.js`);
