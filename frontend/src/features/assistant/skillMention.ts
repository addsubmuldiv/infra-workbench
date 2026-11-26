export function skillMention(text:string,cursor:number){
  const match=/(?:^|[^a-zA-Z0-9_@])@([^\s@]*)$/.exec(text.slice(0,cursor));
  return match?{start:cursor-match[1].length-1,end:cursor,query:match[1].toLocaleLowerCase()}:null;
}
