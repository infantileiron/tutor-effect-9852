import{STATUS}from'../../constants/enums.js';export const tag=map=>value=>`<span class="badge ${value}">${map[value]||value}</span>`;export const badge=tag(STATUS);
