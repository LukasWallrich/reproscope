library(jsonlite)
rows <- fromJSON('out/scoped_results.json',simplifyVector=FALSE)$rows
plot_panel <- function(scale,estimator,influence=FALSE) {
  selected <- Filter(function(r) r$spec$scale==scale && r$spec$location==estimator &&
    (if(influence) r$spec$inference=='centred_bootstrap' && r$spec$multiplicity=='none' && r$spec$interval=='standard' else r$spec$sample=='full'),rows)
  get <- function(key) vapply(selected,function(r) r[[key]],0.)
  x <- get('estimate'); low <- get('ci_lower'); high <- get('ci_upper')
  labels <- vapply(selected,function(r) if(influence) r$spec$sample else paste(r$spec$inference,r$spec$multiplicity,r$spec$interval,sep=' / '),'')
  y <- rev(seq_along(x))
  plot(range(c(low,high,0)),c(.5,length(x)+.5),type='n',yaxt='n',xlab=if(scale=='raw') 'Within-participant difference (original units)' else 'Log ratio (registered x / y)',ylab='',main=paste(scale,estimator,sep=' / '))
  axis(2,at=y,labels=gsub('_',' ',labels),las=2,cex.axis=if(influence) .6 else .7)
  abline(v=0,col='grey70',lty=3)
  color <- ifelse(get('p')<.05,'#17644A','#A14C35')
  segments(low,y,high,y,col=color,lwd=1.5);points(x,y,pch=19,col=color)
  if(influence) {
    full <- which(labels=='full');if(length(full)) abline(v=x[full],col='#243E73',lty=2)
  }
}
for (format in c('svg','png')) {
  if(format=='svg') svg('out/full_sample.svg',width=14,height=9) else png('out/full_sample.png',width=1680,height=1080,res=120)
  par(mfrow=c(2,2),mar=c(4,17,3,1),oma=c(2,0,2,0))
  for(scale in c('raw','log_ratio')) for(estimator in c('mean','trim20')) plot_panel(scale,estimator)
  mtext('Full sample: separate scales and location functionals',outer=TRUE,side=3,line=.2,cex=1.2)
  mtext('Whiskers: unadjusted 95% intervals. Standard: t or percentile; BCa: bias-corrected/accelerated. Green: selected p adjustment < .05.',outer=TRUE,side=1,line=.5,cex=.75)
  dev.off()
  if(format=='svg') svg('out/influence.svg',width=14,height=15) else png('out/influence.png',width=1680,height=1800,res=120)
  par(mfrow=c(2,2),mar=c(4,9,3,1),oma=c(2,0,2,0))
  for(scale in c('raw','log_ratio')) for(estimator in c('mean','trim20')) plot_panel(scale,estimator,TRUE)
  mtext('Every leave-one-participant-out sample: influence diagnostics',outer=TRUE,side=3,line=.2,cex=1.2)
  mtext('Centred bootstrap, unadjusted p; percentile 95% intervals. Dashed blue: full-sample estimate. Do not pool different panels.',outer=TRUE,side=1,line=.5,cex=.8)
  dev.off()
}
