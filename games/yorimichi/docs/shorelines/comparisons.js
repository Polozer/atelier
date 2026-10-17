'use strict';
function renderCoastComparisons(data, container) {
 if (!container || !(data.comparisons || []).length) return;
 const heading=document.createElement('h2');heading.textContent='Reference to game.';container.append(heading);
 for (const comparison of data.comparisons) {
  const article=document.createElement('article');article.className='coast-comparison';
  const title=document.createElement('h3');title.textContent=comparison.title;article.append(title);
  if (comparison.note) {const note=document.createElement('p');note.textContent=comparison.note;article.append(note);}
  const pair=document.createElement('div');pair.className='coast-comparison-pair';
  for (const [src,label] of [[comparison.reference,'Sunburst reference'],[comparison.capture,'In-game revision']]) {
   const figure=document.createElement('figure');const link=document.createElement('a');link.href=src;
   const image=document.createElement('img');image.src=src;image.alt=comparison.title+' — '+label;image.loading='lazy';
   const caption=document.createElement('figcaption');caption.textContent=label;
   link.append(image);figure.append(link,caption);pair.append(figure);
  }
  article.append(pair);container.append(article);
 }
 container.hidden=false;
}
