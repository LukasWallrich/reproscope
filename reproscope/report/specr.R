# Export already-verified results with specr; this script never refits a model.
args <- commandArgs(trailingOnly=TRUE)
suppressPackageStartupMessages({library(specr);library(ggplot2);library(jsonlite)})
p <- fromJSON(args[1], simplifyVector=FALSE)
rows <- p$rows
getnum <- function(r,k) if(is.null(r[[k]])) NA_real_ else as.numeric(r[[k]])
d <- data.frame(estimate=sapply(rows,getnum,'estimate'),conf.low=sapply(rows,getnum,'ci_lower'),conf.high=sapply(rows,getnum,'ci_upper'))
choice_names <- vapply(p$factors,function(f)f$name,character(1))
for(f in p$factors) d[[f$name]] <- vapply(rows,function(r)r$choices[[f$name]],character(1))
if(!length(choice_names)){choice_names <- 'Specification';d$Specification <- 'Single specification'}
ord <- order(d$estimate,seq_len(nrow(d)));d <- d[ord,,drop=FALSE]
colours <- vapply(rows,function(r)r$colour,character(1))[ord]
object <- structure(list(data=d),class='specr.object')
a <- plot(object,type='curve',choices=choice_names,null=p$null)
b <- plot(object,type='choices',choices=choice_names,null=p$null)
# specr defaults to CI-based colours. Use the verified declared test criterion,
# since adjusted tests and the displayed intervals need not encode the same rule.
a$data$color <- colours[a$data$specifications]
b$data$color <- colours[b$data$specifications]
a <- a + labs(y=paste0('Estimate (',p$unit,')'),x=NULL) + theme(text=element_text(size=12),axis.title.y=element_text())
if(isTRUE(p$reference$available)){
 if(!is.null(p$reference$rounding_low)) a <- a + annotate('rect',xmin=-Inf,xmax=Inf,ymin=p$reference$rounding_low,ymax=p$reference$rounding_high,fill='#ad6500',alpha=.10)
 a <- a + geom_hline(yintercept=p$reference$value,linetype='dashed',colour='#ad6500') + labs(subtitle=paste('Paper reports',p$reference$value))
}
labels <- setNames(vapply(p$factors,function(f)f$label,character(1)),vapply(p$factors,function(f)f$name,character(1)))
if(length(p$factors)) b <- b + facet_grid(key~1,scales='free_y',space='free_y',labeller=labeller(key=labels))
b <- b + scale_y_discrete(labels=function(x)vapply(x,function(s)paste(strwrap(s,38),collapse='\n'),character(1))) + labs(x='Specification rank (lowest to highest estimate)') + theme(text=element_text(size=12),strip.text.y=element_text(angle=0))
levels <- sum(vapply(p$factors,function(f)length(f$levels),integer(1)))
# Free-y facets allocate equal height per level. Reserve space for the longest
# wrapped label in every row so multi-line method names cannot overlap.
level_labels <- unlist(lapply(p$factors,function(f)vapply(f$levels,function(l)l$label,character(1))),use.names=FALSE)
label_lines <- max(c(1L,vapply(level_labels,function(s)length(strwrap(s,38)),integer(1))))
choice_height <- max(2,levels*(.16*label_lines+.18)+length(p$factors)*.25+.65)
fig <- cowplot::plot_grid(a,b,ncol=1,labels=c('A','B'),align='v',axis='lrb',rel_heights=c(4,choice_height))
height <- 4+choice_height
ggsave(args[2],fig,device=svglite::svglite,width=12,height=height,limitsize=FALSE)
