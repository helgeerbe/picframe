#include std_head_vs.inc

varying vec2 texcoordoutf;
varying vec2 texcoordoutb;

void main(void) {
  texcoordoutf = texcoord * unif[14].xy - unif[16].xy;
  texcoordoutb = texcoord * unif[15].xy - unif[17].xy;
  gl_Position = modelviewmatrix[1] * vec4(vertex,1.0);
  dist = gl_Position.z;
  gl_PointSize = unib[2][2] / dist;
}