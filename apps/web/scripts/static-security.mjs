import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
const findings=[];
let files=0;
function walk(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){const p=path.join(dir,e.name);if(e.isDirectory())walk(p);else if(/\.(ts|tsx)$/.test(p))inspect(p)}}
function inspect(file){
 files++;const source=ts.createSourceFile(file,fs.readFileSync(file,'utf8'),ts.ScriptTarget.Latest,true);
 function visit(n){
  let label='';
  if(ts.isJsxAttribute(n)&&n.name.getText(source)==='dangerouslySetInnerHTML')label='raw HTML injection sink';
  if(ts.isCallExpression(n)&&['eval','window.eval','globalThis.eval','document.write','document.writeln'].includes(n.expression.getText(source)))label='unsafe execution sink';
  if(ts.isNewExpression(n)&&n.expression.getText(source)==='Function')label='dynamic Function constructor';
  if(ts.isBinaryExpression(n)&&n.operatorToken.kind===ts.SyntaxKind.EqualsToken&&/\.(innerHTML|outerHTML)$/.test(n.left.getText(source)))label='raw HTML assignment';
  if(label)findings.push({file,line:source.getLineAndCharacterOfPosition(n.getStart(source)).line+1,label});
  ts.forEachChild(n,visit);
 }
 visit(source);
}
walk('src');
fs.writeFileSync(process.argv[2]||'frontend-static.json',JSON.stringify({files,findings},null,2));
if(!files||findings.length)process.exitCode=1;
