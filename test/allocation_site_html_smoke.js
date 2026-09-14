// Run the generated report controller with a minimal DOM and exact-u64 fixtures.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8');
const code=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(x=>x[1]).find(x=>x.includes("getElementById('allocation-site-rows')"));
assert(code,'missing allocation site controller');
function element(text=''){return {textContent:text,children:[],appendChild(child){this.children.push(child);}};}
const ids=['18446744073709551600','18446744073709551601'];
const allocations=ids.map(id=>`{"kind":"alloc","size_bytes":18446744073709551600,"site_known":1,"site_function_id":${id},"site_line":12,"site_stack":"${id}:12","repetition":1}`).join(',');
const locations=ids.map(id=>`{"kind":"function","identity_id":${id},"function":"f${id}","source":"test.elisa","compiler_line":12,"line":2,"repetition":1}`).join(',');
const nodes={'allocation-records':element(allocations),'location-records':element(locations),'allocation-site-rows':element(),'allocation-site-status':element()};
vm.runInNewContext(code,{document:{getElementById:id=>nodes[id],createElement:()=>element()}});
assert.equal(nodes['allocation-site-rows'].children.length,2,'u64 identities must not merge');
for(const row of nodes['allocation-site-rows'].children)assert.equal(row.children[2].textContent,'18446744073709551600');
assert(nodes['allocation-site-status'].textContent.includes('0 requests have unknown sites'));
console.log('allocation site HTML controller PASS');
