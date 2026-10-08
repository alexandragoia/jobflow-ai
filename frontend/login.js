'use strict';
document.querySelector('#login-form').addEventListener('submit',async event=>{
 event.preventDefault();const button=event.submitter,status=document.querySelector('#login-status');
 button.disabled=true;status.textContent='Entrando…';
 try{
  const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({password:document.querySelector('#password').value})});
  const data=await response.json();if(!response.ok)throw new Error(data.detail||'No se pudo entrar.');
  window.location.replace('/');
 }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
});
